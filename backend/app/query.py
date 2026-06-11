"""
Data-model-driven query engine for the library list.

Fields are *introspected* from the SQLAlchemy models (Work, Edition, Copy, Author, Series,
Tag), so the filter/sort/search menus are populated from the model and keep working as the
model evolves — nothing is hard-coded per field.

Public:
  fields()                      -> list of {key,entity,column,type,label} for the UI menus
  OPS                           -> {type: [operators]} so the UI offers valid operators
  build_works_query(session, *) -> a SQLAlchemy Query over Work with search/filter/sort applied
"""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text

from . import models as m
from . import search as search_mod

ENTITY_MODELS = {
    "work": m.Work, "edition": m.Edition, "copy": m.Copy,
    "author": m.Author, "series": m.Series, "tag": m.Tag,
}
# Internal/sort-helper/identifier columns we don't expose as user fields.
# cover_path is hidden in favour of the friendlier virtual "Has cover" field below.
_SKIP = {"id", "sort_title", "sort_name", "work_id", "edition_id", "series_id", "cover_path"}

OPS = {
    "text": ["contains", "equals", "not_equals", "empty", "not_empty"],
    "int": ["equals", "gt", "lt", "gte", "lte", "empty", "not_empty"],
    "number": ["equals", "gt", "lt", "gte", "lte", "empty", "not_empty"],
    "date": ["after", "before", "equals", "empty", "not_empty"],
    "datetime": ["after", "before", "empty", "not_empty"],
    "bool": ["true", "false"],
}

# Virtual (computed) fields — not real columns, but filterable/sortable. Keyed by field key.
# "Has cover" is derived from edition.cover_path so it's always accurate (nothing to keep
# in sync). Filter it to "No" to find books that are missing a cover.
_VIRTUAL = {
    "edition.has_cover": {
        "entity": "edition", "type": "bool", "label": "Has cover",
        "help": "Whether the book has a cover image — filter to “No” to find books missing a cover.",
        "cond": (lambda truthy: m.Edition.cover_path.isnot(None) if truthy else m.Edition.cover_path.is_(None)),
    },
}


def _coltype(col):
    t = col.type
    if isinstance(t, Boolean): return "bool"
    if isinstance(t, Integer): return "int"
    if isinstance(t, Numeric): return "number"
    if isinstance(t, Date): return "date"
    if isinstance(t, DateTime): return "datetime"
    if isinstance(t, (String, Text)): return "text"
    return "text"


def fields():
    out = []
    for ename, model in ENTITY_MODELS.items():
        for col in model.__table__.columns:
            if col.name in _SKIP or col.name.endswith("_id"):
                continue
            out.append({
                "key": f"{ename}.{col.name}", "entity": ename, "column": col.name,
                "type": _coltype(col), "label": f"{ename} · {col.name.replace('_', ' ')}",
            })
    for key, v in _VIRTUAL.items():
        ename, cname = key.split(".", 1)
        out.append({"key": key, "entity": ename, "column": cname, "type": v["type"],
                    "label": f"{ename} · {cname.replace('_', ' ')}"})
    return out


_ENTITY_LABEL = {"work": "Work", "edition": "Edition", "copy": "Copy",
                 "author": "Author", "series": "Series", "tag": "Tag"}


def fields_for_ui(session):
    """fields() enriched for the menus: a human-friendly label, a one-line help
    description, and the most frequent example values (enum-like fields only) — so the
    cryptic "copy · kind" entry reads "Medium" with examples "physical, ebook"."""
    from . import datadictionary as dd
    out = []
    for f in fields():
        if f["key"] in _VIRTUAL:
            v = _VIRTUAL[f["key"]]
            examples = ""
            try:
                tot = session.scalar(sa.select(sa.func.count()).select_from(m.Edition)) or 0
                hav = session.scalar(sa.select(sa.func.count()).select_from(m.Edition)
                                     .where(m.Edition.cover_path.isnot(None))) or 0
                examples = f"Yes ({hav}), No ({tot - hav})"
            except Exception:
                examples = ""
            out.append({**f, "label": v["label"],
                        "entity_label": _ENTITY_LABEL.get(f["entity"], f["entity"].capitalize()),
                        "help": v["help"], "examples": examples})
            continue
        model = ENTITY_MODELS[f["entity"]]
        table, col = model.__table__, model.__table__.columns[f["column"]]
        examples = ""
        try:
            distinct = session.scalar(
                sa.select(sa.func.count(sa.distinct(col))).select_from(table)) or 0
            if f["type"] in ("text", "bool") and 0 < distinct <= 40:
                rows = session.execute(
                    sa.select(col, sa.func.count()).select_from(table)
                    .where(col.isnot(None)).group_by(col)
                    .order_by(sa.func.count().desc(), col).limit(2)).all()
                vals = [_cap(str(v)) for v, _c in rows if str(v).strip()]
                examples = ", ".join(vals)
        except Exception:
            examples = ""
        out.append({
            **f,
            "label": dd.label_for(table.name, f["column"]),
            "entity_label": _ENTITY_LABEL.get(f["entity"], f["entity"].capitalize()),
            "help": dd.describe(table.name, f["column"]),
            "examples": examples,
        })
    return out


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _valid(field):
    if not field or "." not in field:
        return False
    if field in _VIRTUAL:
        return True
    ename, cname = field.split(".", 1)
    model = ENTITY_MODELS.get(ename)
    return bool(model) and cname in model.__table__.columns


def _resolve(field):
    ename, cname = field.split(".", 1)
    model = ENTITY_MODELS[ename]
    return ename, model, getattr(model, cname), _coltype(model.__table__.columns[cname])


def _cast(ctype, value):
    if value in (None, ""):
        return value
    try:
        if ctype == "int": return int(value)
        if ctype == "number": return float(value)
        if ctype == "date": return dt.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        if ctype == "datetime": return dt.datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return value
    return value


def _cond(col, ctype, op, value):
    v = _cast(ctype, value)
    if op == "contains": return col.ilike(f"%{value}%")
    if op == "equals": return col == v
    if op == "not_equals": return col != v
    if op in ("gt", "after"): return col > v
    if op in ("lt", "before"): return col < v
    if op == "gte": return col >= v
    if op == "lte": return col <= v
    if op == "empty": return sa.or_(col.is_(None), col == "") if ctype == "text" else col.is_(None)
    if op == "not_empty": return sa.and_(col.isnot(None), col != "") if ctype == "text" else col.isnot(None)
    if op == "true": return col.is_(True)
    if op == "false": return col.is_(False)
    return sa.true()


def _entity_exists(ename, cond):
    """Wrap a leaf condition as a correlated EXISTS against Work (handles to-many cleanly)."""
    if ename == "work":
        return cond
    if ename == "edition":
        return sa.exists(sa.select(m.Edition.id).where(m.Edition.work_id == m.Work.id, cond))
    if ename == "copy":
        return sa.exists(sa.select(m.Copy.id).join(m.Edition, m.Copy.edition_id == m.Edition.id)
                         .where(m.Edition.work_id == m.Work.id, cond))
    if ename == "author":
        return sa.exists(sa.select(m.WorkContributor.id).join(m.Author, m.Author.id == m.WorkContributor.author_id)
                         .where(m.WorkContributor.work_id == m.Work.id, cond))
    if ename == "series":
        return sa.exists(sa.select(m.Series.id).where(m.Series.id == m.Work.series_id, cond))
    if ename == "tag":
        return sa.exists(sa.select(m.WorkTag.id).join(m.Tag, m.Tag.id == m.WorkTag.tag_id)
                         .where(m.WorkTag.work_id == m.Work.id, cond))
    return sa.true()


def _filter_expr(field, op, value):
    if field in _VIRTUAL:
        v = _VIRTUAL[field]
        if op in ("true", "false"):
            return _entity_exists(v["entity"], v["cond"](op == "true"))
        return sa.true()
    ename, model, col, ctype = _resolve(field)
    return _entity_exists(ename, _cond(col, ctype, op, value))


def _fulltext(session, query, q):
    """Ranked full-text search (tsvector ts_rank) + pg_trgm fuzzy/typo tolerance."""
    search_mod.ensure_search_setup(session)
    if session.query(m.WorkSearch).count() == 0 and session.query(m.Work).count() > 0:
        search_mod.reindex(session)                      # lazy first build
    tsq = sa.func.websearch_to_tsquery("simple", q)
    query = query.join(m.WorkSearch, m.WorkSearch.work_id == m.Work.id)
    sim = sa.func.word_similarity(q, m.WorkSearch.text)   # 0..1, typo-tolerant
    query = query.filter(sa.or_(m.WorkSearch.doc.op("@@")(tsq), sim > 0.45))
    rank = sa.func.ts_rank(m.WorkSearch.doc, tsq) + sim   # weighted FTS + fuzzy
    return query, rank


def _sort_expr(field):
    if field == "edition.has_cover":
        # 1 if any of the work's editions has a cover, else 0
        return (sa.select(sa.func.max(sa.case((m.Edition.cover_path.isnot(None), 1), else_=0)))
                .where(m.Edition.work_id == m.Work.id).scalar_subquery())
    ename, model, col, ctype = _resolve(field)
    if ename == "work":
        return col
    if ename == "series":
        return sa.select(col).where(m.Series.id == m.Work.series_id).scalar_subquery()
    if ename == "edition":
        return sa.select(sa.func.min(col)).where(m.Edition.work_id == m.Work.id).scalar_subquery()
    if ename == "copy":
        return (sa.select(sa.func.min(col)).select_from(m.Copy)
                .join(m.Edition, m.Copy.edition_id == m.Edition.id)
                .where(m.Edition.work_id == m.Work.id).scalar_subquery())
    if ename == "author":
        return (sa.select(sa.func.min(col)).select_from(m.WorkContributor)
                .join(m.Author, m.Author.id == m.WorkContributor.author_id)
                .where(m.WorkContributor.work_id == m.Work.id).scalar_subquery())
    if ename == "tag":
        return (sa.select(sa.func.min(col)).select_from(m.WorkTag)
                .join(m.Tag, m.Tag.id == m.WorkTag.tag_id)
                .where(m.WorkTag.work_id == m.Work.id).scalar_subquery())
    return m.Work.sort_title


def build_works_query(session, q=None, search_field=None, filters=None, sort=None, direction="asc", tag=None, collection_id=None):
    query = session.query(m.Work)

    if tag:   # backward-compatible needs-review filter
        query = query.filter(_entity_exists("tag", m.Tag.name == tag))

    if collection_id:   # works in a library collection
        query = query.filter(sa.exists(sa.select(m.CollectionWork.id).where(
            m.CollectionWork.work_id == m.Work.id, m.CollectionWork.collection_id == collection_id)))

    for f in (filters or []):
        field, op, value = f.get("field"), f.get("op"), f.get("value")
        if op and _valid(field):
            try:
                query = query.filter(_filter_expr(field, op, value))
            except Exception:
                pass   # ignore a malformed filter rather than 500

    rank = None
    if q:
        if _valid(search_field):
            query = query.filter(_filter_expr(search_field, "contains", q))   # field-scoped substring
        else:
            query, rank = _fulltext(session, query, q)                        # ranked full-text + fuzzy

    # ordering: explicit sort wins; else relevance (when searching); else title.
    order = []
    if _valid(sort):
        expr = _sort_expr(sort)
        order.append(expr.desc().nullslast() if direction == "desc" else expr.asc().nullslast())
    elif rank is not None:
        order.append(rank.desc())
    else:
        order.append(m.Work.sort_title.asc())
    return query.order_by(*order)
