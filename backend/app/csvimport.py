"""
Flexible CSV import. Accepts a CSV with any columns; detects the useful ones by header,
stages eligible rows (ISBN / ASIN / title), optionally enriches via online lookup, and adds
the chosen rows to the Library or a Wishlist (optionally into a collection).
"""
from __future__ import annotations

import csv
import io
import re

from .encoding import normalize_text

# field -> candidate header names (matched case-insensitively, exact then substring)
FIELD_HEADERS = {
    "isbn": ["isbn13", "isbn_13", "isbn", "isbn10", "isbn_10"],
    "asin": ["asin"],
    "title": ["title", "book title", "name"],
    "authors": ["authors", "author", "author_details", "creator", "by"],
    "publisher": ["publisher", "publishers"],
    "year": ["year", "published year", "publication year", "original publication year",
             "date published", "date_published", "published", "first published"],
}


def detect_columns(headers):
    low = {(h or "").lower().strip(): h for h in (headers or [])}
    out = {}
    for field, names in FIELD_HEADERS.items():
        hit = next((low[n] for n in names if n in low), None)
        if not hit:
            hit = next((h for lh, h in low.items() if any(n in lh for n in names)), None)
        if hit:
            out[field] = hit
    return out


def _year(v):
    mo = re.search(r"\d{4}", v or "")
    return mo.group() if mo else ""


def parse_csv(data: bytes, limit=3000):
    text = data.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text))
    cols = detect_columns(rd.fieldnames or [])
    rows, total = [], 0
    for r in rd:
        total += 1
        if len(rows) >= limit:
            continue
        g = lambda f: normalize_text((r.get(cols[f]) or "").strip()) if f in cols else ""
        authors_raw = g("authors")
        authors = [a.strip() for a in re.split(r"[;|]", authors_raw) if a.strip()] or ([authors_raw] if authors_raw else [])
        title, isbn, asin = g("title"), g("isbn"), g("asin")
        rows.append({
            "title": title, "authors": authors, "isbn": isbn, "asin": asin,
            "publisher": g("publisher"), "year": _year(g("year")),
            "eligible": bool(isbn or asin or title),
        })
    return {"columns": cols, "rows": rows, "total": total, "shown": len(rows)}


def commit(s, rows, destination, collection_id=None, do_lookup=False):
    from .catalog import add_book, add_wishlist
    from .lookup import lookup
    from . import models as m

    added = skipped = enriched = 0
    for row in rows:
        data = dict(row)
        isbn = (data.get("isbn") or "").strip()
        if do_lookup and isbn:
            meta = lookup(isbn)
            if meta:
                enriched += 1
                if not data.get("title"):
                    data["title"] = meta.get("title")
                if not data.get("authors"):
                    data["authors"] = meta.get("authors") or []
                data["publisher"] = data.get("publisher") or meta.get("publisher")
                data["year"] = data.get("year") or _year(str(meta.get("published_date") or ""))
                data["pages"] = meta.get("pages")
                data["description"] = meta.get("description")
        if not (data.get("title") or "").strip():
            skipped += 1
            continue
        if destination == "wishlist":
            data["collection_id"] = collection_id
            add_wishlist(s, data)
        else:
            work, ed, cp = add_book(s, data)
            if collection_id and not s.query(m.CollectionWork).filter_by(
                    collection_id=collection_id, work_id=work.id).first():
                s.add(m.CollectionWork(collection_id=collection_id, work_id=work.id))
                s.commit()
        added += 1
    return {"added": added, "skipped": skipped, "enriched": enriched}
