"""
Data dictionary: a per-database, per-column description of the catalogue with
industry-standard profiling metrics, exportable as CSV from the Stats tab.

For every column of every table it reports: a plain-English description, data type,
nullability, row count, populated/missing counts and fill-rate, cardinality (distinct
values), the most frequent example values, and min/max for numeric & date columns.

The same human-friendly labels, descriptions and example values feed the Library
search/filter/sort menus (see query.fields_for_ui) so the cryptic "copy · kind"
menu entries become understandable.
"""
from __future__ import annotations

import csv
import io

import sqlalchemy as sa
from sqlalchemy import Date, DateTime, Integer, Numeric

from . import models as m
from .db import engine

# Columns we never profile by value (secrets / binary / search blobs).
_NO_VALUES = {
    "users.password_hash", "cover_images.data", "work_search.doc", "work_search.text",
    "settings.value",
}
# Above this distinct-count a column is treated as free-text: no example values.
_EXAMPLE_MAX_CARDINALITY = 60

# Friendly label + plain-English description, keyed "<table>.<column>".
# Tables use the real __tablename__. Anything not listed falls back to _generic().
FIELD_META: dict[str, tuple[str, str]] = {
    # --- authors ---
    "authors.canonical_name": ("Author name", "The author's display name (canonical form), e.g. \"Ursula K. Le Guin\"."),
    "authors.sort_name": ("Author (sort)", "Surname-first form used only for alphabetical sorting, e.g. \"Le Guin, Ursula K.\"."),
    "authors.birth_year": ("Author birth year", "Year the author was born, when known."),
    "authors.death_year": ("Author death year", "Year the author died, when known."),
    "authors.complete_flag": ("Author record complete?", "Curator flag marking an author record as fully checked."),
    "author_name_forms.name_form": ("Author name variant", "An alternative spelling/transliteration of the author's name (e.g. the Greek form), kept verbatim and searchable."),
    # --- series / tags ---
    "series.name": ("Series", "Name of the book series this work belongs to."),
    "tags.name": ("Genre / tag", "A genre or free-form label attached to works (the catalogue's subject tags)."),
    # --- works ---
    "works.title": ("Title", "The work's title (edition-independent)."),
    "works.sort_title": ("Title (sort)", "Title with leading articles dropped, used only for alphabetical sorting."),
    "works.original_language": ("Original language", "Language the work was originally written in, when known."),
    "works.series_position": ("Position in series", "This work's number within its series (e.g. \"2\" or \"2.5\")."),
    "work_contributors.role": ("Contributor role (work)", "How a person contributed to the work: author, editor, etc."),
    "work_identifiers.scheme": ("Work identifier type", "Which external catalogue an id comes from (e.g. goodreads_work, olid_work)."),
    "work_identifiers.value": ("Work identifier", "The identifier value in that external catalogue."),
    # --- editions ---
    "editions.isbn13": ("ISBN-13", "13-digit ISBN of this specific edition."),
    "editions.isbn10": ("ISBN-10", "Older 10-digit ISBN of this edition, when applicable."),
    "editions.publisher": ("Publisher", "Publisher of this edition."),
    "editions.published_date": ("Publication date", "Full publication date of this edition, when known."),
    "editions.published_year": ("Year published", "Publication year (used when only the year is known)."),
    "editions.pages": ("Page count", "Number of pages in this edition."),
    "editions.format": ("Binding / format", "Physical or digital format, e.g. Paperback, Hardcover, ebook."),
    "editions.language": ("Language", "Language of this edition's text."),
    "editions.list_price": ("Cover price", "The publisher's list (cover) price."),
    "editions.list_price_currency": ("Cover price currency", "Currency of the cover price (ISO code, e.g. GBP, EUR)."),
    "editions.cover_path": ("Cover image reference", "Where the cover image lives (\"db:<id>\" for web covers stored in the database, else a backup path)."),
    "editions.description": ("Description / blurb", "The edition's synopsis or back-cover text."),
    "edition_contributors.role": ("Contributor role (edition)", "Edition-specific contributor role, e.g. translator, narrator, illustrator."),
    "edition_identifiers.scheme": ("Edition identifier type", "Which external catalogue an id comes from (isbn13, asin, goodreads, google, …)."),
    "edition_identifiers.value": ("Edition identifier", "The identifier value in that external catalogue."),
    # --- copies (the physical/digital item you own) ---
    "copies.kind": ("Medium", "What kind of item this owned copy is: physical (a printed book), ebook (a file), or audio (an audiobook)."),
    "copies.copy_type": ("Copy purpose", "Why you hold this copy: reading (a reading copy), collectible (kept for collection value), photocopy, lending (to lend out), or archive."),
    "copies.condition": ("Condition", "Whether the copy is new or used."),
    "copies.condition_grade": ("Condition grade", "Collector grade of the copy: Fine, VG (very good), Good, Fair or Poor."),
    "copies.location": ("Shelf location", "Where the copy physically sits (shelf/area code) — or the file path for an e-book."),
    "copies.signed": ("Signed copy?", "Whether this copy is signed by the author."),
    "copies.acquired_date": ("Date acquired", "When you obtained this copy."),
    "copies.acquisition_price": ("Acquisition price", "What you paid for this copy."),
    "copies.acquisition_currency": ("Acquisition currency", "Currency of the acquisition price (ISO code)."),
    "copies.current_value": ("Current value", "Estimated current resale/insurance value of this copy."),
    "copies.current_value_currency": ("Current value currency", "Currency of the current value (ISO code)."),
    "copies.notes": ("Copy notes", "Free-text provenance and personal comments about this copy."),
    "copies.file_ref": ("E-book file path", "Absolute path of the e-book file (set by the folder scan)."),
    "copies.legacy_book_uuid": ("Legacy Book-Catalogue id", "The original Book Catalogue book_uuid, kept as the import join key."),
    # --- reading / loans ---
    "reading_sessions.started": ("Reading started", "Date you started reading this copy."),
    "reading_sessions.finished": ("Reading finished", "Date you finished reading this copy."),
    "reading_sessions.progress_pct": ("Reading progress %", "How far through the copy you are (0–100)."),
    "reading_sessions.status": ("Reading status", "unread, reading, or read."),
    "loans.borrower": ("Borrower", "Who the copy is lent to."),
    "loans.lent_date": ("Lent date", "When the copy was lent out."),
    "loans.due_date": ("Loan due date", "When the loaned copy is due back."),
    "loans.returned_date": ("Loan returned date", "When the loaned copy was returned (empty = still out)."),
    # --- collections / wishlist ---
    "collections.name": ("Collection name", "Name of a user-defined grouping (a library shelf-set or a wishlist)."),
    "collections.kind": ("Collection type", "library (groups owned works) or wishlist (groups wanted items)."),
    "wishlist_items.title": ("Wishlist title", "Title of a wanted (not-yet-owned) book."),
    "wishlist_items.target_price": ("Wishlist target price", "The price you're willing to pay for a wishlist item."),
    "wishlist_items.currency": ("Wishlist currency", "Currency of the target price (ISO code)."),
    "wishlist_items.priority": ("Wishlist priority", "Your priority ranking for acquiring this item."),
    "wishlist_items.notes": ("Wishlist notes", "Free-text notes about a wishlist item."),
    # --- maps / sources / settings / users / enrichment ---
    "library_maps.area": ("Map area (location prefix)", "The shelf-location prefix this 3-D map covers (e.g. \"UK\")."),
    "library_maps.name": ("Map name", "Human name of the 3-D shelf map (e.g. \"UK Office\")."),
    "library_maps.asset_path": ("Map asset path", "Path to the map widget HTML."),
    "enrichment_sources.key": ("Source key", "Internal id of a metadata source (openlibrary, politeianet, …)."),
    "enrichment_sources.name": ("Source name", "Display name of the metadata source."),
    "enrichment_sources.enabled": ("Source enabled?", "Whether this source is used during enrichment."),
    "enrichment_sources.priority": ("Source priority", "Merge order — lower number wins a field when sources disagree."),
    "settings.key": ("Setting key", "Name of an app setting (e.g. ebooks_dir, skin)."),
    "users.username": ("Username", "Login name of an app user."),
    "users.role": ("User role", "Access level: admin, user, or readonly."),
    "cover_images.content_type": ("Cover MIME type", "Image type of a stored web cover (e.g. image/jpeg)."),
    "cover_images.source": ("Cover source", "Where a stored web cover came from (e.g. biblionet)."),
    "enrichment_runs.mode": ("Enrichment run mode", "How a run was performed (dry_run)."),
    "enrichment_runs.status": ("Enrichment run status", "pending, committed, or discarded."),
    "enrichment_runs.source": ("Enrichment run source", "Which metadata source the run used."),
    "enrichment_runs.note": ("Enrichment run note", "Free-text note about the run."),
    "enrichment_proposals.entity_type": ("Proposal target", "Whether a proposed change applies to a work or an edition."),
    "enrichment_proposals.field": ("Proposed field", "Which field a proposal would change."),
    "enrichment_proposals.current_value": ("Proposal current value", "The existing value before the proposed change."),
    "enrichment_proposals.proposed_value": ("Proposed new value", "The value the source suggests."),
    "enrichment_proposals.change_type": ("Proposal change type", "add (the field was empty) or change (it differs)."),
    "enrichment_proposals.source": ("Proposal source", "Which metadata source suggested the change."),
    "enrichment_proposals.selected": ("Proposal selected?", "Whether the curator picked this proposal to commit."),
    "enrichment_proposals.committed": ("Proposal committed?", "Whether this proposal was written to the catalogue."),
    "enrichment_proposals.committed_at": ("Proposal committed at", "When the proposal was committed."),
}

_TYPE_NAMES = {Integer: "integer", Numeric: "number", Date: "date", DateTime: "datetime"}


def _generic(table: str, column: str) -> tuple[str, str]:
    pretty = column.replace("_", " ").strip().capitalize()
    if column == "id":
        return (f"{table} id", "Internal unique identifier (random hex; not user-facing).")
    if column.endswith("_id"):
        ref = column[:-3]
        return (f"{pretty}", f"Foreign key linking to the {ref} it belongs to.")
    if column == "created_at":
        return ("Created at", "Timestamp when this row was first created.")
    if column == "updated_at":
        return ("Updated at", "Timestamp when this row was last modified.")
    return (pretty, f"{pretty} ({table}).")


def label_for(table: str, column: str) -> str:
    meta = FIELD_META.get(f"{table}.{column}")
    return meta[0] if meta else _generic(table, column)[0]


def describe(table: str, column: str) -> str:
    meta = FIELD_META.get(f"{table}.{column}")
    return meta[1] if meta else _generic(table, column)[1]


def _coltype_name(col) -> str:
    for cls, name in _TYPE_NAMES.items():
        if isinstance(col.type, cls):
            return name
    return "text"


def column_stats(session, table, col, *, with_values=True) -> dict:
    """Profiling metrics for one column (industry-standard data-dictionary fields)."""
    key = f"{table.name}.{col.name}"
    total = session.scalar(sa.select(sa.func.count()).select_from(table)) or 0
    populated = session.scalar(sa.select(sa.func.count(col)).select_from(table)) or 0
    missing = total - populated
    distinct = session.scalar(
        sa.select(sa.func.count(sa.distinct(col))).select_from(table)) or 0
    out = {
        "rows": total, "populated": populated, "missing": missing,
        "fill_rate": round(populated / total, 4) if total else 0.0,
        "cardinality": distinct, "examples": "", "min": "", "max": "",
    }
    if isinstance(col.type, (Integer, Numeric, Date, DateTime)):
        out["min"] = session.scalar(sa.select(sa.func.min(col)).select_from(table))
        out["max"] = session.scalar(sa.select(sa.func.max(col)).select_from(table))
        out["min"] = "" if out["min"] is None else str(out["min"])
        out["max"] = "" if out["max"] is None else str(out["max"])
    if with_values and key not in _NO_VALUES and 0 < distinct <= _EXAMPLE_MAX_CARDINALITY \
            and not isinstance(col.type, (Numeric,)):
        rows = session.execute(
            sa.select(col, sa.func.count()).select_from(table)
            .where(col.isnot(None)).group_by(col)
            .order_by(sa.func.count().desc(), col).limit(5)).all()
        out["examples"] = "; ".join(f"{v} ({c})" for v, c in rows if str(v).strip())
    return out


def _mapped_tables():
    """(class, table) for every mapped model, in a stable, readable order."""
    seen, out = set(), []
    for mapper in m.Base.registry.mappers:
        t = mapper.local_table
        if t is not None and t.name not in seen:
            seen.add(t.name)
            out.append((mapper.class_, t))
    out.sort(key=lambda ct: ct[1].name)
    return out


def _db_name() -> str:
    try:
        return engine.url.database or "database"
    except Exception:
        return "database"


def dictionary_rows(session) -> list[dict]:
    db = _db_name()
    rows = []
    for _cls, table in _mapped_tables():
        for col in table.columns:
            st = column_stats(session, table, col)
            rows.append({
                "database": db,
                "table": table.name,
                "column": col.name,
                "label": label_for(table.name, col.name),
                "description": describe(table.name, col.name),
                "type": _coltype_name(col),
                "nullable": "yes" if col.nullable else "no",
                "primary_key": "yes" if col.primary_key else "no",
                "rows": st["rows"],
                "populated": st["populated"],
                "missing": st["missing"],
                "fill_rate_%": round(st["fill_rate"] * 100, 1),
                "distinct_values": st["cardinality"],
                "min": st["min"],
                "max": st["max"],
                "most_frequent_values": st["examples"],
            })
        if table.name == "editions":
            rows.append(_has_cover_row(session, db))
    return rows


def _has_cover_row(session, db) -> dict:
    """A derived (virtual) column: whether an edition has a cover. Not stored — computed
    from cover_path — but documented here and filterable in the Library (Edition · Has cover)."""
    total = session.scalar(sa.select(sa.func.count()).select_from(m.Edition)) or 0
    have = session.scalar(sa.select(sa.func.count()).select_from(m.Edition)
                          .where(m.Edition.cover_path.isnot(None))) or 0
    return {
        "database": db, "table": "editions", "column": "has_cover (derived)",
        "label": "Has cover",
        "description": "DERIVED from cover_path: yes if the edition has a cover image. "
                       "Filterable/sortable in the Library (Edition · Has cover) to find books missing a cover.",
        "type": "bool", "nullable": "no", "primary_key": "no",
        "rows": total, "populated": total, "missing": 0,
        "fill_rate_%": 100.0, "distinct_values": 2 if 0 < have < total else 1,
        "min": "", "max": "", "most_frequent_values": f"Yes ({have}); No ({total - have})",
    }


_CSV_FIELDS = ["database", "table", "column", "label", "description", "type", "nullable",
               "primary_key", "rows", "populated", "missing", "fill_rate_%",
               "distinct_values", "min", "max", "most_frequent_values"]


def csv_bytes(session) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_FIELDS)
    w.writeheader()
    for r in dictionary_rows(session):
        w.writerow(r)
    return ("﻿" + buf.getvalue()).encode("utf-8")   # BOM → Greek-safe in Excel
