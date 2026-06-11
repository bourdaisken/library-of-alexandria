"""
Targeted re-pull for records still damaged after the mojibake pass.

For each edition whose description (or its work's title) is garbled beyond repair, re-fetch
fresh bibliographic data BY ISBN via the merged multi-source lookup (OpenLibrary + BiblioNet
+ Google + Library of Congress + DNB + custom catalogues) and OVERWRITE the damaged fields
with clean values. Everything curated/local is preserved: shelf location, condition, signed,
acquisition/value, notes, format, and pages — non-damaged bibliographic fields are only
gap-filled (never clobbered), and the cover is fetched only if missing.

Author-name corruption is NOT auto-replaced here (shared entity, ambiguous mapping) — it's
reported for manual Find-match/edit.
"""
from __future__ import annotations

from .lookup import lookup, normalise_isbn
from .mojibake import _is_residual
from .encoding import normalize_text
from .catalog import _sort_title
from .search import reindex
from . import models as m


def _year(raw):
    import re
    mo = re.search(r"(1[4-9]\d{2}|20\d{2})", str(raw or ""))
    return int(mo.group(1)) if mo else None


def propose_by_title(session, threshold: float = 0.90) -> list[dict]:
    """DRY proposal: for each garbled-description/title edition, search OpenLibrary/Google/
    BiblioNet by title+author and pick the best candidate by TITLE similarity to the book's
    existing (intact) title. Writes NOTHING — returns rows for a review CSV. `status`:
    match (ratio >= threshold) / low-confidence / no-results."""
    import difflib
    from . import titlesearch
    from .dq import _norm

    targets = []
    for e in session.query(m.Edition).all():
        dmg_desc = _is_residual(e.description)
        dmg_title = bool(e.work) and _is_residual(e.work.title)
        if dmg_desc or dmg_title:
            targets.append((e, dmg_desc, dmg_title))

    rows = []
    for e, dmg_desc, dmg_title in targets:
        title = e.work.title if e.work else ""
        authors = [c.author.canonical_name for c in e.work.contributors] if e.work else []
        query = f"{title} {authors[0] if authors else ''}".strip()
        try:
            cands = titlesearch.search(["google", "openlibrary", "biblionet"], query) or []
        except Exception:
            cands = []
        best, best_r = None, 0.0
        for c in cands:
            r = difflib.SequenceMatcher(None, _norm(title), _norm(c.get("title") or "")).ratio()
            better = r > best_r + 0.02
            tie_pref = abs(r - best_r) <= 0.02 and c.get("description") and not (best and best.get("description"))
            if better or tie_pref:
                best, best_r = c, max(r, best_r)
        isbn = (best.get("isbn") if best else "") or ""
        desc = (best.get("description") if best else "") or ""
        cover = (best.get("cover_url") if best else "") or ""
        pages = (best.get("pages") if best else "") or ""
        year = (best.get("published_date") if best else "") or ""
        # Confident title match → use its ISBN to pull a richer record (descriptions come
        # from the ISBN data path, not search).
        if best and best_r >= threshold and isbn:
            rich = lookup(normalise_isbn(isbn), session) or {}
            desc = (rich.get("description") or desc) or ""
            cover = cover or (rich.get("cover_url") or "")
            pages = pages or (rich.get("pages") or "")
            year = year or (rich.get("published_date") or "")
        if not cands:
            status = "no-results"
        elif best_r < threshold:
            status = "low-confidence"
        elif desc:
            status = "match+desc"
        else:
            status = "match-isbn-only"
        rows.append({
            "field": "title" if dmg_title else "description",
            "edition_id": e.id,
            "book": title,
            "authors": "; ".join(authors),
            "existing_value": (e.description or "")[:200] if dmg_desc else title,
            "status": status,
            "match_ratio": round(best_r, 2),
            "matched_title": (best.get("title") if best else ""),
            "source": (best.get("source") if best else ""),
            "proposed_isbn": isbn,
            "proposed_year": year,
            "proposed_pages": pages,
            "proposed_cover_url": cover,
            "proposed_description": desc,
        })
    return rows


def repull(session, apply: bool = False) -> dict:
    report = {"fixed": [], "no_isbn": [], "no_data": [], "author_residual": []}

    targets = []
    for e in session.query(m.Edition).all():
        dmg_desc = _is_residual(e.description)
        dmg_title = bool(e.work) and _is_residual(e.work.title)
        if dmg_desc or dmg_title:
            targets.append((e, dmg_desc, dmg_title))

    for e, dmg_desc, dmg_title in targets:
        owner = e.work.title if e.work else ""
        isbn = normalise_isbn(e.isbn13 or e.isbn10)
        if not isbn:
            report["no_isbn"].append({"edition": e.id, "book": owner})
            continue
        meta = lookup(isbn, session) or {}
        if not meta:
            report["no_data"].append({"edition": e.id, "isbn": isbn, "book": owner})
            continue

        changed = []
        # Overwrite damaged fields with fresh CLEAN values.
        if dmg_desc:
            nd = normalize_text(meta.get("description"))
            if nd and not _is_residual(nd):
                if apply:
                    e.description = nd
                changed.append("description")
        if dmg_title and e.work:
            nt = normalize_text(meta.get("title"))
            if nt and not _is_residual(nt):
                if apply:
                    e.work.title = nt
                    e.work.sort_title = _sort_title(nt)
                changed.append("title")
        # Gap-fill only (preserve curated values).
        if not e.publisher and meta.get("publisher"):
            if apply:
                e.publisher = normalize_text(meta["publisher"])
            changed.append("publisher(filled)")
        if not e.published_year and _year(meta.get("published_date")):
            if apply:
                e.published_year = _year(meta["published_date"])
            changed.append("year(filled)")
        if not e.pages and meta.get("pages"):
            try:
                pg = int(meta["pages"])
                if apply:
                    e.pages = pg
                changed.append("pages(filled)")
            except (TypeError, ValueError):
                pass
        if not e.cover_path and meta.get("cover_url"):
            if apply:
                from .covers import store_cover_from_url
                if store_cover_from_url(session, e, meta["cover_url"], source=meta.get("source") or "repull"):
                    changed.append("cover")
            else:
                changed.append("cover?")

        if changed:
            report["fixed"].append({"edition": e.id, "book": owner, "isbn": isbn,
                                    "source": meta.get("source"), "changed": changed})
        elif dmg_desc or dmg_title:
            # ISBN found + data returned, but nothing usable/clean to replace with.
            report["no_data"].append({"edition": e.id, "isbn": isbn, "book": owner,
                                      "note": "no clean replacement in sources"})

    # Author-name residuals: report only (manual).
    for a in session.query(m.Author).all():
        if _is_residual(a.canonical_name):
            report["author_residual"].append({"author_id": a.id, "name": a.canonical_name})

    if apply:
        session.commit()
        reindex(session)
    return report
