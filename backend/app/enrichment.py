"""
Opt-in network enrichment with full human control.

Flow (never runs during import):
  1. DRY RUN  -> fetch from sources, compute a field-level DIFF vs existing records,
                 persist as EnrichmentProposal rows. NOTHING is written to your data.
  2. REVIEW   -> inspect the diff; each proposal is `add` (field empty) or `change` (differs).
  3. COMMIT   -> apply, in one of these modes:
        - "selected" : only proposals you picked (per-record / per-field)
        - "all"      : apply every proposal in the run ("enrich all")
        - "none"     : discard the run, write nothing ("do nothing")

Only fields where the source has a value AND it differs from (or fills) the current value
become proposals — so a dry run on an already-complete record yields zero proposals.
Every fetched string is normalize_text()'d, so enrichment can never introduce mojibake.
"""
from __future__ import annotations

import datetime as dt

from .db import Session
from .encoding import normalize_text
from .lookup import lookup
from . import models as m

# Edition fields we enrich, with how to read the source dict and coerce the value.
EDITION_FIELDS = {
    "description": lambda src: src.get("description"),
    "publisher": lambda src: src.get("publisher"),
    "pages": lambda src: src.get("pages"),
    "published_year": lambda src: _year(src.get("published_date")),
}


def _year(raw):
    if not raw:
        return None
    s = str(raw)
    for i in range(len(s) - 3):
        if s[i:i + 4].isdigit():
            return int(s[i:i + 4])
    return None


def _coerce(field, value):
    if value is None:
        return None
    if field in ("pages", "published_year"):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return normalize_text(str(value))


def dry_run(session=None, edition_ids=None, note=None):
    """Create an EnrichmentRun + proposals (no record writes). Returns the run."""
    s = session or Session()
    run = m.EnrichmentRun(mode="dry_run", status="pending", note=note)
    s.add(run)
    s.flush()

    q = s.query(m.Edition).filter(m.Edition.isbn13.isnot(None))
    if edition_ids:
        q = q.filter(m.Edition.id.in_(edition_ids))

    for ed in q:
        meta = lookup(ed.isbn13 or ed.isbn10)
        if not meta:
            continue
        for field, getter in EDITION_FIELDS.items():
            proposed = _coerce(field, getter(meta))
            if proposed is None or proposed == "":
                continue
            current = getattr(ed, field)
            if current is not None and str(current).strip() != "":
                if str(current).strip() == str(proposed).strip():
                    continue                       # identical -> no proposal
                change_type = "change"
            else:
                change_type = "add"
            s.add(m.EnrichmentProposal(
                run_id=run.id, entity_type="edition", entity_id=ed.id,
                field=field, current_value=(str(current) if current is not None else None),
                proposed_value=str(proposed), change_type=change_type,
                source=meta.get("source"),
            ))
        # Cover (binary): propose only when the edition has no cover yet. The proposed
        # value is the image URL; on commit it is downloaded and stored in the DB.
        cover_url = meta.get("cover_url")
        if cover_url and not ed.cover_path:
            s.add(m.EnrichmentProposal(
                run_id=run.id, entity_type="edition", entity_id=ed.id,
                field="cover", current_value=None, proposed_value=str(cover_url),
                change_type="add", source=meta.get("source"),
            ))
    s.commit()
    return run


def diff(session, run_id):
    """Return the run's proposals (the reviewable diff)."""
    s = session or Session()
    run = s.get(m.EnrichmentRun, run_id)
    if not run:
        return None
    return {
        "run_id": run.id,
        "status": run.status,
        "proposals": [
            {
                "id": p.id, "entity_type": p.entity_type, "entity_id": p.entity_id,
                "field": p.field, "current": p.current_value, "proposed": p.proposed_value,
                "change_type": p.change_type, "source": p.source,
                "selected": p.selected, "committed": p.committed,
            }
            for p in run.proposals
        ],
    }


def select(session, run_id, proposal_ids, value=True):
    """Mark specific proposals selected (for a later 'selected' commit)."""
    s = session or Session()
    ids = set(proposal_ids or [])
    for p in s.query(m.EnrichmentProposal).filter(m.EnrichmentProposal.run_id == run_id):
        if p.id in ids:
            p.selected = bool(value)
    s.commit()


def _apply(s, p: m.EnrichmentProposal):
    ent = s.get(m.Edition if p.entity_type == "edition" else m.Work, p.entity_id)
    if ent is None:
        return False
    if p.field == "cover":
        from .covers import store_cover_from_url
        if not store_cover_from_url(s, ent, p.proposed_value, source=p.source or "enrichment"):
            return False   # download failed — leave uncommitted so it can be retried
    else:
        setattr(ent, p.field, _coerce(p.field, p.proposed_value))
    p.committed = True
    p.committed_at = dt.datetime.now(dt.timezone.utc)
    return True


def apply_candidate(session, edition_id, cand: dict, update_title=False, add_author_forms=False):
    """Apply a user-CHOSEN match candidate to an edition: fill empty metadata fields,
    add a cover if missing, and set the ISBN if the edition had none. Only fills gaps —
    never overwrites values you already have.

    Two opt-in extras (the user reviewed the match, so these are allowed to act):
      update_title       -> replace the work title with the candidate's (fixes transliterations)
      add_author_forms   -> add the candidate's author name(s) as ALTERNATE name forms on the
                            primary author, KEEPING the existing canonical name (and indexing
                            the new form so it's searchable).
    Returns the list of fields applied."""
    s = session or Session()
    ed = s.get(m.Edition, edition_id)
    if ed is None:
        return None
    work = s.get(m.Work, ed.work_id)
    applied = []

    if update_title and work and cand.get("title"):
        nt = normalize_text(cand["title"])
        if nt and nt != work.title:
            from .catalog import _sort_title
            work.title = nt
            work.sort_title = _sort_title(nt)
            applied.append("title")

    if add_author_forms and work and work.contributors and cand.get("authors"):
        author = work.contributors[0].author   # primary author keeps its canonical (Latin) name
        existing = {nf.name_form for nf in author.name_forms}
        for name in cand["authors"]:
            n = normalize_text(name)
            if n and n not in existing:
                author.name_forms.append(m.AuthorNameForm(name_form=n))
                existing.add(n)
                if "author name" not in applied:
                    applied.append("author name")

    def fill(field, value):
        value = _coerce(field, value)
        if value in (None, ""):
            return
        cur = getattr(ed, field)
        if cur is None or str(cur).strip() == "":
            setattr(ed, field, value)
            applied.append(field)

    fill("description", cand.get("description"))
    fill("publisher", cand.get("publisher"))
    fill("pages", cand.get("pages"))
    fill("published_year", _year(cand.get("published_date")))
    if not ed.language and cand.get("language"):
        ed.language = normalize_text(cand["language"]); applied.append("language")

    # ISBN-13 only if the edition has none.
    isbn = "".join(c for c in str(cand.get("isbn") or "") if c.isdigit())
    if not ed.isbn13 and len(isbn) == 13:
        ed.isbn13 = isbn
        ed.identifiers.append(m.EditionIdentifier(scheme="isbn13", value=isbn))
        applied.append("isbn")

    # Cover (download + store) only if the edition has none.
    if not ed.cover_path and cand.get("cover_url"):
        from .covers import store_cover_from_url
        if store_cover_from_url(s, ed, cand["cover_url"], source=cand.get("source") or "match"):
            applied.append("cover")

    s.commit()
    if applied:
        from .search import reindex
        reindex(s, ed.work_id)
    return applied


def commit(session, run_id, mode="selected"):
    """
    Apply a run's proposals.
      mode="selected" -> only proposals with selected=True
      mode="all"      -> every proposal ("enrich all")
      mode="none"     -> discard, write nothing ("do nothing")
    """
    s = session or Session()
    run = s.get(m.EnrichmentRun, run_id)
    if not run:
        return None
    if mode == "none":
        run.status = "discarded"
        s.commit()
        return {"run_id": run.id, "status": run.status, "applied": 0}

    applied = 0
    for p in run.proposals:
        if p.committed:
            continue
        if mode == "all" or (mode == "selected" and p.selected):
            if _apply(s, p):
                applied += 1
    run.status = "committed"
    s.commit()
    return {"run_id": run.id, "status": run.status, "applied": applied, "mode": mode}
