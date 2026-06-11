"""
Catalog write service: add a book to the LIBRARY (work/edition/copy) or the WISHLIST.

Shared get-or-create dedup (Work by primary-author+title, Edition by ISBN13) so adding a
book you already own as a different edition/copy attaches correctly instead of duplicating.
All inbound text passes through normalize_text() — the encoding guarantee applies to manual
entry and online lookups alike.
"""
from __future__ import annotations

import datetime as dt

from .config import Config
from .encoding import normalize_text
from .search import reindex
from . import models as m


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _norm_isbn(raw):
    if not raw:
        return None, None
    s = "".join(c for c in str(raw) if c.isdigit() or c in "Xx").upper()
    if len(s) == 13:
        return s, None
    if len(s) == 10:
        return None, s
    return None, None


def _sort_title(t):
    import re
    mo = re.match(r"^(A|An|The)\s+(.*)$", t or "", re.I)
    return f"{mo.group(2)}, {mo.group(1)}" if mo else (t or "")


def _get_author(s, sort_name):
    a = s.query(m.Author).filter(m.Author.sort_name == sort_name).first()
    if not a:
        a = m.Author(canonical_name=sort_name, sort_name=sort_name)
        a.name_forms.append(m.AuthorNameForm(name_form=sort_name))
        s.add(a)
        s.flush()
    return a


def _get_series(s, name):
    if not name:
        return None
    sr = s.query(m.Series).filter(m.Series.name == name).first()
    if not sr:
        sr = m.Series(name=name)
        s.add(sr)
        s.flush()
    return sr


def _get_tag(s, name):
    t = s.query(m.Tag).filter(m.Tag.name == name).first()
    if not t:
        t = m.Tag(name=name)
        s.add(t)
        s.flush()
    return t


def add_book(s, data: dict):
    """Create (or attach to) Work -> Edition -> Copy from a structured payload."""
    authors = [normalize_text(a).strip() for a in (data.get("authors") or []) if a and a.strip()]
    primary = authors[0] if authors else "Unknown"
    title = normalize_text((data.get("title") or "").strip()) or "(untitled)"

    work = (
        s.query(m.Work)
        .join(m.WorkContributor, m.WorkContributor.work_id == m.Work.id)
        .join(m.Author, m.Author.id == m.WorkContributor.author_id)
        .filter(m.Work.title == title, m.Author.sort_name == primary)
        .first()
    )
    if not work:
        work = m.Work(title=title, sort_title=_sort_title(title))
        series = normalize_text(data.get("series"))
        if series:
            work.series = _get_series(s, series)
            work.series_position = data.get("series_position")
        s.add(work)
        s.flush()
        for tok in authors:
            au = _get_author(s, tok)
            if tok not in [nf.name_form for nf in au.name_forms]:
                au.name_forms.append(m.AuthorNameForm(name_form=tok))
            if not any(wc.author_id == au.id for wc in work.contributors):
                work.contributors.append(m.WorkContributor(author_id=au.id, role="author"))
        seen = set()
        for tag_name in (data.get("tags") or []):
            tn = normalize_text(tag_name).strip()
            if not tn:
                continue
            tag = _get_tag(s, tn)
            if tag.id not in seen:
                seen.add(tag.id)
                work.tags.append(m.WorkTag(tag_id=tag.id))

    isbn13, isbn10 = _norm_isbn(data.get("isbn"))
    pub = normalize_text(data.get("publisher")) or None
    year = _i(data.get("year"))
    fmt = normalize_text(data.get("format")) or None
    edition = None
    if isbn13:
        edition = s.query(m.Edition).filter(m.Edition.isbn13 == isbn13).first()
    if not edition:
        lp = _f(data.get("list_price"))
        edition = m.Edition(
            work_id=work.id, isbn13=isbn13, isbn10=isbn10, publisher=pub,
            published_year=year, pages=_i(data.get("pages")),
            format=fmt, language=normalize_text(data.get("language")) or None,
            list_price=lp, list_price_currency=(data.get("currency") or Config.DEFAULT_CURRENCY) if lp else None,
            description=normalize_text(data.get("description")) or None,
        )
        s.add(edition)
        s.flush()
        if isbn13:
            edition.identifiers.append(m.EditionIdentifier(scheme="isbn13", value=isbn13))
        if isbn10:
            edition.identifiers.append(m.EditionIdentifier(scheme="isbn10", value=isbn10))
        asin = (data.get("asin") or "").strip()
        if asin:
            edition.identifiers.append(m.EditionIdentifier(scheme="asin", value=asin))

    cp = data.get("copy") or {}
    aprice = _f(cp.get("acquisition_price"))
    copy = m.Copy(
        edition_id=edition.id,
        kind=cp.get("kind") or "physical",
        copy_type=cp.get("copy_type") or "reading",
        condition=cp.get("condition"),
        condition_grade=cp.get("condition_grade"),
        location=normalize_text(cp.get("location")) or None,
        signed=bool(cp.get("signed")),
        acquired_date=_today_if(cp.get("acquired_today")),
        acquisition_price=aprice,
        acquisition_currency=(cp.get("currency") or Config.DEFAULT_CURRENCY) if aprice else None,
        notes=normalize_text(cp.get("notes")) or None,
        file_ref=cp.get("file_ref") or None,
    )
    s.add(copy)
    s.commit()
    reindex(s, work.id)
    return work, edition, copy


def update_book(s, work_id, data: dict):
    """Flat edit of a work + one of its editions + one of its copies (ids optional)."""
    work = s.get(m.Work, work_id)
    if not work:
        return None

    if "title" in data and (data.get("title") or "").strip():
        work.title = normalize_text(data["title"].strip())
        work.sort_title = _sort_title(work.title)
    if "series" in data:
        series = normalize_text(data.get("series"))
        work.series = _get_series(s, series) if series else None
        work.series_position = data.get("series_position") or None
    if "authors" in data:
        work.contributors.clear()
        s.flush()
        for tok in [normalize_text(a).strip() for a in (data.get("authors") or []) if a and a.strip()]:
            au = _get_author(s, tok)
            if tok not in [nf.name_form for nf in au.name_forms]:
                au.name_forms.append(m.AuthorNameForm(name_form=tok))
            work.contributors.append(m.WorkContributor(author_id=au.id, role="author"))
    if "tags" in data:
        work.tags.clear()
        s.flush()
        seen = set()
        for tn in [normalize_text(t).strip() for t in (data.get("tags") or []) if t and t.strip()]:
            tag = _get_tag(s, tn)
            if tag.id not in seen:
                seen.add(tag.id)
                work.tags.append(m.WorkTag(tag_id=tag.id))

    ed = s.get(m.Edition, data["edition_id"]) if data.get("edition_id") else (work.editions[0] if work.editions else None)
    if ed:
        if "isbn" in data:
            ed.isbn13, ed.isbn10 = _norm_isbn(data.get("isbn"))
        for fld, key in [("publisher", "publisher"), ("language", "language"), ("format", "format")]:
            if key in data:
                setattr(ed, fld, normalize_text(data.get(key)) or None)
        if "year" in data:
            ed.published_year = _i(data.get("year"))
        if "pages" in data:
            ed.pages = _i(data.get("pages"))
        if "list_price" in data:
            ed.list_price = _f(data.get("list_price"))
        if "description" in data:
            ed.description = normalize_text(data.get("description")) or None

    cp_in = data.get("copy") or {}
    cp = s.get(m.Copy, data["copy_id"]) if data.get("copy_id") else (ed.copies[0] if ed and ed.copies else None)
    if cp and cp_in:
        for fld in ("kind", "copy_type", "condition", "condition_grade"):
            if fld in cp_in:
                setattr(cp, fld, cp_in.get(fld) or None)
        if "location" in cp_in:
            cp.location = normalize_text(cp_in.get("location")) or None
        if "signed" in cp_in:
            cp.signed = bool(cp_in.get("signed"))
        if "notes" in cp_in:
            cp.notes = normalize_text(cp_in.get("notes")) or None
        if "acquisition_price" in cp_in:
            cp.acquisition_price = _f(cp_in.get("acquisition_price"))

    s.commit()
    reindex(s, work.id)
    return work


def add_wishlist(s, data: dict):
    """Create a wishlist item (a wanted book you don't own yet)."""
    title = normalize_text((data.get("title") or "").strip())
    authors = ", ".join(normalize_text(a) for a in (data.get("authors") or []) if a)
    display = f"{title} — {authors}" if authors else title
    item = m.WishlistItem(
        title=display or None,
        collection_id=data.get("collection_id") or None,
        target_price=_f(data.get("target_price")),
        currency=data.get("currency") or Config.DEFAULT_CURRENCY,
        priority=_i(data.get("priority")),
        notes=normalize_text(data.get("notes")) or _isbn_note(data.get("isbn")),
    )
    s.add(item)
    s.commit()
    return item


def _today_if(flag):
    return dt.date.today() if flag else None


def _isbn_note(isbn):
    isbn = (isbn or "").strip()
    return f"ISBN {isbn}" if isbn else None
