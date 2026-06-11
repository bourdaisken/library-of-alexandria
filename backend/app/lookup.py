"""
Online metadata lookup (OpenLibrary + Google Books). Used ONLY by the opt-in enrichment
flow — never during import. 

Returns a normalized dict; every text value passes through normalize_text() so nothing
fetched from the network can introduce mojibake.
"""
from __future__ import annotations

import requests

from .config import Config
from .encoding import normalize_text


def normalise_isbn(isbn: str | None) -> str | None:
    if not isbn:
        return None
    s = "".join(ch for ch in isbn if ch.isdigit() or ch in "Xx").upper()
    return s or None


def _norm(d: dict) -> dict:
    return {k: (normalize_text(v) if isinstance(v, str) else v) for k, v in d.items()}


def _from_openlibrary(isbn: str) -> dict | None:
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    try:
        r = requests.get(url, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json().get(f"ISBN:{isbn}")
    except (requests.RequestException, ValueError):
        return None
    if not data:
        return None
    return _norm({
        "title": data.get("title"),
        "authors": [a.get("name") for a in data.get("authors", []) if a.get("name")],
        "publisher": (data.get("publishers") or [{}])[0].get("name"),
        "published_date": data.get("publish_date"),
        "pages": data.get("number_of_pages"),
        "description": (data.get("notes") if isinstance(data.get("notes"), str) else None),
        "cover_url": (data.get("cover") or {}).get("large"),
        "source": "openlibrary",
    })


def _from_google(isbn: str) -> dict | None:
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    if Config.GOOGLE_BOOKS_API_KEY:
        url += f"&key={Config.GOOGLE_BOOKS_API_KEY}"
    try:
        r = requests.get(url, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        items = r.json().get("items")
    except (requests.RequestException, ValueError):
        return None
    if not items:
        return None
    v = items[0].get("volumeInfo", {})
    return _norm({
        "title": v.get("title"),
        "authors": [normalize_text(a) for a in v.get("authors", [])],
        "publisher": v.get("publisher"),
        "published_date": v.get("publishedDate"),
        "pages": v.get("pageCount"),
        "description": v.get("description"),
        "cover_url": (v.get("imageLinks") or {}).get("thumbnail"),
        "source": "google",
    })


def _from_biblionet(isbn: str) -> dict | None:
    """BiblioNet (biblionet.gr) — the largest Greek-language catalogue. Fills metadata
    + covers for Greek books that OpenLibrary/Google miss. Greek text normalized."""
    from .biblionet import lookup_isbn
    meta = lookup_isbn(isbn)
    if not meta:
        return None
    meta = _norm(meta)
    meta["authors"] = [normalize_text(a) for a in (meta.get("authors") or [])]
    return meta


def _from_politeianet(isbn: str) -> dict | None:
    """Politeianet (politeianet.gr) — premium Greek bookshop; very rich metadata
    (often better than BiblioNet for Greek titles). Greek text normalized."""
    from .politeianet import lookup_isbn
    meta = lookup_isbn(isbn)
    if not meta:
        return None
    meta = _norm(meta)
    meta["authors"] = [normalize_text(a) for a in (meta.get("authors") or [])]
    return meta


def _from_sru_builtin(key):
    """ISBN fetcher for a pre-coded SRU library (Library of Congress, German DNB).
    Uses the library's dedicated ISBN index, so the server's match is trusted."""
    def f(isbn):
        from .sru import LIBRARIES, search_isbn
        lib = LIBRARIES.get(key)
        if not lib:
            return None
        meta = search_isbn(lib["isbn"], isbn, strict=False)
        if meta:
            meta["source"] = lib["name"]
        return meta
    return f


# Built-in fetchers, keyed for the configurable sources registry. Same source pool the
# Find-match picker uses — Enrich queries them all by ISBN and MERGES the results.
FETCHERS = {
    "openlibrary": _from_openlibrary,
    "politeianet": _from_politeianet,
    "google": _from_google,
    "biblionet": _from_biblionet,
    "loc": _from_sru_builtin("loc"),
    "dnb": _from_sru_builtin("dnb"),
}

DEFAULT_SOURCES = [
    {"key": "openlibrary", "name": "OpenLibrary", "priority": 10},
    {"key": "politeianet", "name": "Politeianet (Greek)", "priority": 12},
    {"key": "biblionet", "name": "BiblioNet (Greek)", "priority": 15},
    {"key": "google", "name": "Google Books", "priority": 20},
    {"key": "loc", "name": "Library of Congress", "priority": 30},
    {"key": "dnb", "name": "German DNB", "priority": 35},
]


def ensure_default_sources(s):
    """Seed the source registry, and add any newly-shipped default source that's missing
    (so existing installs pick up BiblioNet without a manual step)."""
    from . import models as m
    existing = {k for (k,) in s.query(m.EnrichmentSource.key).all()}
    added = False
    for d in DEFAULT_SOURCES:
        if d["key"] not in existing:
            s.add(m.EnrichmentSource(key=d["key"], name=d["name"], enabled=True, priority=d["priority"]))
            added = True
    if added:
        s.commit()


def active_source_keys(s) -> list[str]:
    from . import models as m
    ensure_default_sources(s)
    rows = (s.query(m.EnrichmentSource)
            .filter(m.EnrichmentSource.enabled.is_(True))
            .order_by(m.EnrichmentSource.priority).all())
    return [r.key for r in rows if r.key in FETCHERS]


def lookup(isbn: str | None, session=None) -> dict | None:
    """Fetch metadata for an ISBN by MERGING every enabled source (highest priority wins
    each field): OpenLibrary, BiblioNet, Google, Library of Congress, German DNB, plus any
    user-added SRU catalogues. So one book can take its description from one source, its
    publisher/year from a library catalogue, and its cover from a third."""
    isbn = normalise_isbn(isbn)
    if not isbn:
        return None
    from .db import Session
    s = session or Session()
    merged: dict = {}
    used: list[str] = []

    def absorb(meta, label):
        if not meta:
            return
        used.append(meta.get("source") or label)
        for k, v in meta.items():
            if k == "source" or v in (None, "", []):
                continue
            if not merged.get(k):
                merged[k] = v

    for key in active_source_keys(s):     # enabled built-ins, by priority
        try:
            absorb(FETCHERS[key](isbn), key)
        except Exception:
            continue

    try:                                   # user-added SRU catalogues (exact-ISBN match)
        from .settings import get_setting
        from .sru import search_isbn
        for cs in (get_setting("custom_sources") or []):
            if cs.get("url"):
                meta = search_isbn(cs["url"], isbn, strict=True)
                if meta:
                    meta["source"] = cs.get("name")
                absorb(meta, cs.get("name") or "custom")
    except Exception:
        pass

    if not merged:
        return None
    merged["source"] = " + ".join(dict.fromkeys(used)) if used else None
    return merged
