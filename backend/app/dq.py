"""
Data-quality studio: model-driven field harmonisation.

- field_values(field)  -> distinct values + counts for any model field (the field picker is
  populated from /api/fields, so it tracks the data model).
- cluster_values(field) -> groups of near-duplicate values (normalized-equality + fuzzy
  difflib similarity) so you can merge typos / case / spacing / punctuation variants.
- replace_value(field, from[], to) -> apply across the DB. Plain columns are bulk-updated;
  author/series/tag are true MERGES (references reassigned, duplicate rows removed).

Note: similarity is string-based — it catches case/spacing/punctuation/typos (softcover →
Paperback), not cross-script transliterations (Σπανδάγος vs Spandagos share no trigrams).
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from sqlalchemy import func

from . import models as m
from .query import ENTITY_MODELS, _valid
from .search import reindex

MERGE_FIELDS = {"author.canonical_name", "series.name", "tag.name"}


def _col(field):
    ename, cname = field.split(".", 1)
    return ENTITY_MODELS[ename], getattr(ENTITY_MODELS[ename], cname)


def field_values(s, field, limit=1000):
    if not _valid(field):
        return []
    model, col = _col(field)
    rows = s.query(col, func.count()).group_by(col).order_by(func.count().desc()).limit(limit).all()
    return [{"value": v, "count": n} for v, n in rows if v is not None and str(v) != ""]


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cluster_values(s, field, threshold=0.84, max_fuzzy=700):
    """Return clusters of similar values. Each cluster: {values:[{value,count}], suggested}."""
    vals = field_values(s, field)
    by_key = {}
    for v in vals:
        by_key.setdefault(_norm(v["value"]), []).append(v)
    keys = list(by_key.keys())

    # union-find over normalized keys; merge identical keys (already grouped) + fuzzy-similar keys
    parent = {k: k for k in keys}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        parent[find(a)] = find(b)

    if len(keys) <= max_fuzzy:
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if abs(len(a) - len(b)) <= max(3, len(a) * 0.4) and difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
                    union(a, b)

    groups = {}
    for k in keys:
        groups.setdefault(find(k), []).extend(by_key[k])

    clusters = []
    for members in groups.values():
        if len({mm["value"] for mm in members}) < 2:
            continue   # only show clusters with >1 distinct value
        members.sort(key=lambda x: -x["count"])
        clusters.append({"values": members, "suggested": members[0]["value"]})
    clusters.sort(key=lambda c: -sum(v["count"] for v in c["values"]))
    return clusters


# ---- merges for relationship entities ----
def _merge_authors(s, from_values, to):
    target = s.query(m.Author).filter(m.Author.canonical_name == to).first()
    if not target:
        target = m.Author(canonical_name=to, sort_name=to)
        target.name_forms.append(m.AuthorNameForm(name_form=to))
        s.add(target); s.flush()
    forms = {nf.name_form for nf in target.name_forms}
    for src in s.query(m.Author).filter(m.Author.canonical_name.in_(from_values)).all():
        if src.id == target.id:
            continue
        for wc in s.query(m.WorkContributor).filter_by(author_id=src.id).all():
            if s.query(m.WorkContributor).filter_by(work_id=wc.work_id, author_id=target.id, role=wc.role).first():
                s.delete(wc)
            else:
                wc.author_id = target.id
        for ec in s.query(m.EditionContributor).filter_by(author_id=src.id).all():
            if s.query(m.EditionContributor).filter_by(edition_id=ec.edition_id, author_id=target.id, role=ec.role).first():
                s.delete(ec)
            else:
                ec.author_id = target.id
        for nf in src.name_forms:
            if nf.name_form not in forms:
                target.name_forms.append(m.AuthorNameForm(name_form=nf.name_form)); forms.add(nf.name_form)
        s.delete(src)
    s.commit()


def _merge_series(s, from_values, to):
    target = s.query(m.Series).filter_by(name=to).first()
    if not target:
        target = m.Series(name=to); s.add(target); s.flush()
    for src in s.query(m.Series).filter(m.Series.name.in_(from_values)).all():
        if src.id == target.id:
            continue
        s.query(m.Work).filter_by(series_id=src.id).update({m.Work.series_id: target.id}, synchronize_session=False)
        s.delete(src)
    s.commit()


def _merge_tags(s, from_values, to):
    target = s.query(m.Tag).filter_by(name=to).first()
    if not target:
        target = m.Tag(name=to); s.add(target); s.flush()
    for src in s.query(m.Tag).filter(m.Tag.name.in_(from_values)).all():
        if src.id == target.id:
            continue
        for wt in s.query(m.WorkTag).filter_by(tag_id=src.id).all():
            if s.query(m.WorkTag).filter_by(work_id=wt.work_id, tag_id=target.id).first():
                s.delete(wt)
            else:
                wt.tag_id = target.id
        s.delete(src)
    s.commit()


def replace_value(s, field, from_values, to):
    """Harmonise: set every `from_values` to `to` for `field`, across the whole DB."""
    from_values = [v for v in (from_values or []) if v]
    if not _valid(field) or not from_values or to is None:
        return {"error": "field, from-values and a target are required"}
    to = str(to)
    if field == "author.canonical_name":
        _merge_authors(s, from_values, to)
    elif field == "series.name":
        _merge_series(s, from_values, to)
    elif field == "tag.name":
        _merge_tags(s, from_values, to)
    else:
        model, col = _col(field)
        s.query(model).filter(col.in_(from_values)).update({col: to}, synchronize_session=False)
        s.commit()
    reindex(s)   # keep full-text index in step
    return {"ok": True, "field": field, "merged": len(from_values), "to": to}
