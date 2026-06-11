"""
Data-quality pass: repair mojibake across ALL catalog text (the CORE encoding guarantee).

Uses ftfy.fix_encoding (+ NFC) — proven safe: it reverses classic double-encoding
(JosÃ©→José, SÃ£o→São, ContrÃ´le→Contrôle) and leaves Greek / clean text UNTOUCHED.
Entity-name fields (author/series/tag) are repaired via the data-quality MERGE path, so a
fixed value that collides with an existing one is merged rather than duplicated.

Lossy/odd corruptions ftfy can't reverse (e.g. "Contrãole" for "Contrôle", where bytes were
replaced not re-encoded) are NOT changed — they're reported as residuals for manual merge.
"""
from __future__ import annotations

import unicodedata

import ftfy

from . import models as m
from .encoding import _MOJIBAKE, REPLACEMENT
from .search import reindex

# Plain text columns — repaired in place (id-targeted UPDATE).
_PLAIN = [
    ("work.title", m.Work, "title"),
    ("work.sort_title", m.Work, "sort_title"),
    ("edition.publisher", m.Edition, "publisher"),
    ("edition.description", m.Edition, "description"),
    ("copy.location", m.Copy, "location"),
    ("copy.notes", m.Copy, "notes"),
    ("author.sort_name", m.Author, "sort_name"),
    ("author_name_form.name_form", m.AuthorNameForm, "name_form"),
    ("wishlist.title", m.WishlistItem, "title"),
    ("wishlist.notes", m.WishlistItem, "notes"),
    ("collection.name", m.Collection, "name"),
]
# Entity-name columns — repaired via dq.replace_value (true MERGE on collision).
_MERGE = [
    ("author.canonical_name", m.Author, "canonical_name"),
    ("series.name", m.Series, "name"),
    ("tag.name", m.Tag, "name"),
]


def fix(value):
    """Safe mojibake repair for one value (NFC + ftfy encoding fix). No-op on clean text."""
    if not value or not isinstance(value, str):
        return value
    return unicodedata.normalize("NFC", ftfy.fix_encoding(value))


def _suspicious(value: str) -> bool:
    """Looks damaged: replacement char or Ã-style mojibake leftover."""
    return bool(value) and (REPLACEMENT in value or _MOJIBAKE.search(value) is not None)


def _acceptable(new: str) -> bool:
    """Only auto-apply a repair whose RESULT is fully clean and stable — so we never swap
    one broken value for another, and never write a lossy replacement char (the apostrophe
    is already gone in '?ï¿½s'; turning it into '?�s' helps nobody)."""
    return bool(new) and not _suspicious(new) and fix(new) == new


def _is_residual(val: str) -> bool:
    """A value that's damaged but NOT cleanly auto-fixable (reported, never auto-changed)."""
    if not val:
        return False
    new = fix(val)
    return (new != val and not _acceptable(new)) or _suspicious(val)


def residual_report(session) -> list[dict]:
    """Detailed rows for every unrepairable value, with context for locating + acting on it.
    Columns: field, book_or_owner, record_id, value, ftfy_attempt."""
    rows = []

    def add(field, owner, rid, val):
        rows.append({"field": field, "book_or_owner": owner or "", "record_id": rid,
                     "value": val, "ftfy_attempt": fix(val)})

    for w in session.query(m.Work).all():
        for attr in ("title", "sort_title"):
            v = getattr(w, attr)
            if _is_residual(v):
                add(f"work.{attr}", w.title, w.id, v)
    for e in session.query(m.Edition).all():
        owner = e.work.title if e.work else ""
        for attr in ("publisher", "description"):
            v = getattr(e, attr)
            if _is_residual(v):
                add(f"edition.{attr}", owner, e.id, v)
    for c in session.query(m.Copy).all():
        owner = c.edition.work.title if c.edition and c.edition.work else ""
        for attr in ("location", "notes"):
            v = getattr(c, attr)
            if _is_residual(v):
                add(f"copy.{attr}", owner, c.id, v)
    for a in session.query(m.Author).all():
        for attr in ("canonical_name", "sort_name"):
            v = getattr(a, attr)
            if _is_residual(v):
                add(f"author.{attr}", a.canonical_name, a.id, v)
    for nf in session.query(m.AuthorNameForm).all():
        if _is_residual(nf.name_form):
            add("author_name_form.name_form", nf.name_form, nf.id, nf.name_form)
    for sr in session.query(m.Series).all():
        if _is_residual(sr.name):
            add("series.name", sr.name, sr.id, sr.name)
    for tg in session.query(m.Tag).all():
        if _is_residual(tg.name):
            add("tag.name", tg.name, tg.id, tg.name)
    for wi in session.query(m.WishlistItem).all():
        for attr in ("title", "notes"):
            v = getattr(wi, attr)
            if _is_residual(v):
                add(f"wishlist.{attr}", wi.title, wi.id, v)
    return rows


def scan(session):
    """Return {plain:[(label,id,old,new)], merge:[(field,old,new)], residual:[(label,sample)]}.
    Writes nothing."""
    plain, merge, residual = [], [], []

    for label, model, attr in _PLAIN:
        col = getattr(model, attr)
        for pk, val in session.query(model.id, col).filter(col.isnot(None)).all():
            new = fix(val)
            if new != val and _acceptable(new):
                plain.append((label, pk, val, new))
            elif (new != val and not _acceptable(new)) or _suspicious(val):
                residual.append((label, val))

    for field, model, attr in _MERGE:
        col = getattr(model, attr)
        seen = set()
        for (val,) in session.query(col).filter(col.isnot(None)).distinct().all():
            if not val or val in seen:
                continue
            seen.add(val)
            new = fix(val)
            if new != val and _acceptable(new):
                merge.append((field, val, new))
            elif (new != val and not _acceptable(new)) or _suspicious(val):
                residual.append((field, val))

    return {"plain": plain, "merge": merge, "residual": residual}


def apply(session):
    """Repair everything scan() found auto-fixable; returns counts. Reindexes at the end."""
    from .dq import replace_value
    result = scan(session)
    by_model = {label: (model, attr) for label, model, attr in _PLAIN}

    for label, pk, old, new in result["plain"]:
        model, attr = by_model[label]
        row = session.get(model, pk)
        if row is not None:
            setattr(row, attr, new)
    session.commit()

    merged = 0
    for field, old, new in result["merge"]:
        try:
            replace_value(session, field, [old], new)
            merged += 1
        except Exception:
            session.rollback()

    reindex(session)
    return {"plain_fixed": len(result["plain"]), "merged": merged,
            "residual": len(result["residual"])}
