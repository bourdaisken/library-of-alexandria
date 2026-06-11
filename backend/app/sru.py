"""
SRU (Search/Retrieve via URL) client for user-added library catalogues.

National libraries (Library of Congress, British Library, German DNB, the Greek
NLG, etc.) expose SRU endpoints that return standardized MARCXML or Dublin Core.
The user registers a source as a URL TEMPLATE containing `{q}` (Admin → Custom
catalogue sources); we substitute the search term, fetch, and parse records into
the common candidate shape used by the Find-match picker.

Stdlib only; never raises (returns [] on any network/parse error). Covers aren't in
MARC, so when a record has an ISBN we point cover_url at OpenLibrary's cover-by-ISBN.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _ln(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _digits(s: str) -> str:
    return re.sub(r"[^0-9Xx]", "", s or "")


def _clean(s):
    """Strip C0/C1 control chars (e.g. MARC non-sorting markers in German records)."""
    if not s:
        return s
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", s).strip(" /:,")


def _year(raw: str) -> str | None:
    m = re.search(r"(1[4-9]\d{2}|20\d{2})", raw or "")
    return m.group(1) if m else None


def _from_marc(rec) -> dict | None:
    controlfields, datafields = {}, []
    for el in rec:
        ln = _ln(el.tag)
        if ln == "controlfield":
            controlfields[el.get("tag")] = (el.text or "").strip()
        elif ln == "datafield":
            sub = {}
            for sf in el:
                if _ln(sf.tag) == "subfield":
                    sub.setdefault(sf.get("code"), []).append((sf.text or "").strip())
            datafields.append((el.get("tag"), sub))

    def df(tag, *codes):
        for t, sub in datafields:
            if t == tag:
                parts = [v for c in codes for v in sub.get(c, [])]
                if parts:
                    return " ".join(parts)
        return None

    title = df("245", "a", "b")
    if not title:
        return None
    isbn = _digits(df("020", "a") or "")
    lang = df("041", "a")
    cf008 = controlfields.get("008", "")
    if not lang and len(cf008) >= 38:
        lang = cf008[35:38].strip() or None
    return {
        "title": title.strip(" /:,"),
        "author": df("100", "a") or df("110", "a") or df("700", "a"),
        "publisher": df("264", "b") or df("260", "b"),
        "year": _year(df("264", "c") or df("260", "c") or cf008),
        "isbn": isbn,
        "language": lang,
    }


def _from_dc(rec) -> dict | None:
    vals: dict[str, list[str]] = {}
    for el in rec.iter():
        ln = _ln(el.tag)
        if ln in ("title", "creator", "publisher", "date", "identifier", "language") and el.text:
            vals.setdefault(ln, []).append(el.text.strip())
    if not vals.get("title"):
        return None
    isbn = ""
    for idv in vals.get("identifier", []):
        d = _digits(idv)
        if len(d) in (10, 13):
            isbn = d
            break
    year = None
    for d in vals.get("date", []):
        year = _year(d)
        if year:
            break
    return {
        "title": vals["title"][0],
        "author": (vals.get("creator") or [None])[0],
        "publisher": (vals.get("publisher") or [None])[0],
        "year": year, "isbn": isbn,
        "language": (vals.get("language") or [None])[0],
    }


# Pre-coded national-library catalogues that conform (SRU → MARCXML). Each has a
# title/keyword query (for Find match) and a dedicated ISBN query (for Enrich).
LIBRARIES = {
    "loc": {
        "name": "Library of Congress",
        "title": ("http://lx2.loc.gov:210/lcdb?version=1.1&operation=searchRetrieve"
                  "&maximumRecords=10&recordSchema=marcxml&query=bath.any={q}"),
        "isbn": ("http://lx2.loc.gov:210/lcdb?version=1.1&operation=searchRetrieve"
                 "&maximumRecords=5&recordSchema=marcxml&query=bath.isbn%3D{q}"),
    },
    "dnb": {
        "name": "German DNB",
        "title": ("https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve"
                  "&maximumRecords=10&recordSchema=MARC21-xml&query={q}"),
        "isbn": ("https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve"
                 "&maximumRecords=5&recordSchema=MARC21-xml&query=NUM%3D{q}"),
    },
}


def search_isbn(url_template: str, isbn: str, strict: bool = False, timeout: float = 15.0) -> dict | None:
    """Best single record for an ISBN, or None. strict=True requires the record's own
    ISBN to match (use for keyword templates; a dedicated ISBN index can trust the server)."""
    rows = search(url_template, isbn, timeout=timeout) or []
    if strict:
        want = _digits(isbn)
        rows = [r for r in rows if _digits(r.get("isbn") or "") == want]
    return rows[0] if rows else None


def search(url_template: str, query: str, limit: int = 10, timeout: float = 15.0) -> list[dict]:
    """Run an SRU search and return candidate dicts. url_template should contain {q}."""
    q = urllib.parse.quote((query or "").strip())
    if not q:
        return []
    url = url_template.replace("{q}", q) if "{q}" in url_template else (url_template + q)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            xml = r.read()
    except Exception:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out = []
    for rec in root.iter():
        if _ln(rec.tag) != "record":
            continue
        is_marc = any(_ln(c.tag) in ("datafield", "controlfield", "leader") for c in rec)
        if is_marc:
            d = _from_marc(rec)
        elif any(_ln(c.tag) in ("title", "creator") for c in rec.iter()):
            d = _from_dc(rec)
        else:
            continue
        if not d:
            continue
        isbn = d.get("isbn") or ""
        title = _clean(d["title"])
        if not title:
            continue
        out.append({
            "title": title, "subtitle": None,
            "authors": [_clean(d["author"])] if d.get("author") else [],
            "published_date": d.get("year"), "pages": None, "description": None,
            "publisher": _clean(d.get("publisher")), "language": d.get("language"),
            "isbn": isbn or None,
            "cover_url": (f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg?default=false"
                         if len(isbn) in (10, 13) else None),
            "source": None,   # set by the caller to the source's display name
        })
        if len(out) >= limit:
            break
    return out
