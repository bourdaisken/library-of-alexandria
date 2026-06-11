"""
CSV export of the catalog and wishlist — backward-compatible, flexible copies of all data.

Encoding: written as UTF-8 **with BOM** (utf-8-sig) so Greek and every other script open
correctly in Excel/LibreOffice and never appear as gibberish. Data is already NFC-normalized
on the way in, so exports are byte-faithful round-trips.

Grain: one row per COPY (the natural unit, like Book Catalogue) — a book owned twice yields
two rows sharing the same bibliographic columns.
"""
from __future__ import annotations

import csv
import io

from . import models as m

LIBRARY_HEADER = [
    "work_title", "authors", "series", "series_position",
    "isbn13", "isbn10", "publisher", "year", "pages", "format", "language",
    "list_price", "list_price_currency",
    "kind", "copy_type", "condition", "condition_grade", "location", "signed",
    "acquired_date", "acquisition_price", "acquisition_currency",
    "current_value", "current_value_currency",
    "notes", "tags", "goodreads_id", "asin", "legacy_book_uuid",
]

WISHLIST_HEADER = ["title", "target_price", "currency", "priority", "notes"]


def _ident(edition, scheme):
    for i in edition.identifiers:
        if i.scheme == scheme:
            return i.value
    return ""


def _library_rows(s):
    q = (
        s.query(m.Copy)
        .join(m.Edition, m.Edition.id == m.Copy.edition_id)
        .join(m.Work, m.Work.id == m.Edition.work_id)
        .order_by(m.Work.sort_title)
    )
    for cp in q:
        ed, w = cp.edition, cp.edition.work
        yield [
            w.title,
            "|".join(c.author.canonical_name for c in w.contributors),
            w.series.name if w.series else "",
            w.series_position or "",
            ed.isbn13 or "", ed.isbn10 or "", ed.publisher or "",
            ed.published_year or "", ed.pages or "", ed.format or "", ed.language or "",
            ed.list_price if ed.list_price is not None else "", ed.list_price_currency or "",
            cp.kind, cp.copy_type, cp.condition or "", cp.condition_grade or "",
            cp.location or "", "yes" if cp.signed else "",
            cp.acquired_date or "",
            cp.acquisition_price if cp.acquisition_price is not None else "", cp.acquisition_currency or "",
            cp.current_value if cp.current_value is not None else "", cp.current_value_currency or "",
            cp.notes or "", ", ".join(t.tag.name for t in w.tags),
            _ident(ed, "goodreads"), _ident(ed, "asin"), cp.legacy_book_uuid or "",
        ]


def library_csv(s) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(LIBRARY_HEADER)
    for row in _library_rows(s):
        w.writerow(row)
    return buf.getvalue().encode("utf-8-sig")   # BOM => Excel-safe Greek/UTF-8


def wishlist_csv(s) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(WISHLIST_HEADER)
    for it in s.query(m.WishlistItem).order_by(m.WishlistItem.created_at.desc()):
        w.writerow([
            it.title or "",
            it.target_price if it.target_price is not None else "",
            it.currency or "",
            it.priority if it.priority is not None else "",
            it.notes or "",
        ])
    return buf.getvalue().encode("utf-8-sig")
