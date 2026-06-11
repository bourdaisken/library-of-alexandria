"""
Folder-scan e-book importer.

Point the catalog at a folder of e-book / comic files (EBOOKS_DIR); for each
file we read embedded bibliographic metadata (ebookmeta.py), fall back to an
ISBN parsed from the filename, optionally enrich from the online sources, and
record the file as an **e-book Copy** in the catalog. It reads e-book files directly — no second container, no service to keep running.

Idempotent: a Copy is keyed on its absolute file path (Copy.file_ref). Re-scanning
a folder skips files already cataloged, so it is safe to run repeatedly.

Encoding: catalog.add_book() routes every string through normalize_text(), so the
Greek-safe / no-mojibake guarantee holds for filenames and embedded metadata alike.
"""
from __future__ import annotations

import re

from .catalog import add_book
from .ebookmeta import scan_directory
from . import models as m

# Lowercase extension → display format stored on the Edition.
_FORMAT = {
    ".epub": "EPUB", ".pdf": "PDF", ".docx": "DOCX", ".doc": "DOC",
    ".mobi": "MOBI", ".azw": "AZW", ".azw3": "AZW3", ".azw4": "AZW4",
    ".pdb": "PDB", ".prc": "PRC", ".fb2": "FB2",
    ".djvu": "DjVu", ".djv": "DjVu",
    ".cbz": "CBZ", ".cbr": "CBR", ".cbt": "CBT",
}


def _isbn_from_name(stem: str) -> str | None:
    """Pull a 13- or 10-digit ISBN out of a filename stem (common in downloads)."""
    digits = re.sub(r"[-\s]", "", stem)
    m13 = re.search(r"(97[89]\d{10})", digits)
    if m13:
        return m13.group(1)
    m10 = re.search(r"(?<!\d)(\d{9}[\dXx])(?!\d)", digits)
    if m10:
        return m10.group(1).upper()
    return None


def _enrich_empty(data: dict, isbn: str, session) -> None:
    """Fill only the empty fields of *data* from an online ISBN lookup."""
    from .lookup import lookup
    meta = lookup(isbn, session=session)
    if not meta:
        return
    if not data.get("title") and meta.get("title"):
        data["title"] = meta["title"]
    if not data.get("authors") and meta.get("authors"):
        data["authors"] = meta["authors"]
    for key in ("publisher", "pages", "description"):
        if not data.get(key) and meta.get(key):
            data[key] = meta[key]
    if not data.get("year") and meta.get("published_date"):
        mt = re.search(r"\d{4}", str(meta["published_date"]))
        if mt:
            data["year"] = mt.group(0)


def scan_folder(session, root: str | None = None, lookup: bool = False) -> dict:
    """Scan *root* (default Config.EBOOKS_DIR) and catalog each new e-book file.

    Returns {scanned, added, skipped, root}. `skipped` counts files already in
    the catalog (idempotency). Set lookup=True to enrich missing fields online.
    """
    if not root:
        from .settings import get_ebooks_dir
        root = get_ebooks_dir()
    if not root:
        raise NotADirectoryError("No e-book folder configured (set it in Admin → E-book folder).")

    files = scan_directory(root)   # raises NotADirectoryError if the path is bad
    added = skipped = 0

    for entry in files:
        path = entry["path"]
        existing = (
            session.query(m.Copy)
            .filter(m.Copy.kind == "ebook", m.Copy.file_ref == path)
            .first()
        )
        if existing:
            skipped += 1
            continue

        emb = entry.get("embedded") or {}
        title = (emb.get("title") or "").strip() or entry["stem"]
        authors = [a.strip() for a in (emb.get("author") or "").split(",") if a.strip()]
        isbn = emb.get("isbn13") or emb.get("isbn") or _isbn_from_name(entry["stem"])

        data = {
            "title": title,
            "authors": authors,
            "isbn": isbn,
            "publisher": emb.get("publisher") or None,
            "year": emb.get("year") or None,
            "language": emb.get("language") or None,
            "series": emb.get("series") or None,
            "format": _FORMAT.get(entry["ext"], entry["ext"].lstrip(".").upper()),
            "copy": {
                "kind": "ebook",
                "copy_type": "reading",
                "location": "ebook:" + entry["rel_path"],
                "file_ref": path,
            },
        }

        if lookup and isbn:
            try:
                _enrich_empty(data, isbn, session)
            except Exception:
                pass  # enrichment is best-effort; never fail a scan over it

        add_book(session, data)   # commits + reindexes the work
        added += 1

    return {"scanned": len(files), "added": added, "skipped": skipped, "root": str(root)}
