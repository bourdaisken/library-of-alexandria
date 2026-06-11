"""
Online book search for the E-book Metadata Quality tab.

A bare ISBN does a direct Open Library lookup; any other query searches Open
Library and Google Books, merges, and dedupes by normalised title. Returns a
list of BookMetadata. Network errors degrade to fewer/no results, never raise.
"""
from __future__ import annotations

import re

import requests

from .config import Config
from .ebookmeta import BookMetadata, title_sort_key, author_sort_key, normalise_author

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
OPEN_LIBRARY_ISBN = "https://openlibrary.org/api/books"
GOOGLE_BOOKS_SEARCH = "https://www.googleapis.com/books/v1/volumes"


def _clean_isbn(raw: str) -> str:
    return re.sub(r"[-\s]", "", raw or "")


def _ol_search(query: str) -> list[BookMetadata]:
    params = {
        "q": query,
        "fields": "title,author_name,first_publish_year,publisher,isbn,publish_place,language",
        "limit": 10,
    }
    try:
        r = requests.get(OPEN_LIBRARY_SEARCH, params=params, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        docs = r.json().get("docs", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for doc in docs:
        m = BookMetadata(source="Open Library")
        m.title = doc.get("title", "")
        m.title_sort = title_sort_key(m.title)
        authors = doc.get("author_name") or []
        m.author = ", ".join(normalise_author(a) for a in authors[:3])
        m.author_sort = author_sort_key(m.author)
        m.year = str(doc.get("first_publish_year", "") or "")
        pubs = doc.get("publisher") or []
        m.publisher = pubs[0] if pubs else ""
        places = doc.get("publish_place") or []
        m.city = places[0] if places else ""
        for raw in (doc.get("isbn") or []):
            isbn = _clean_isbn(raw)
            if len(isbn) == 13:
                m.isbn13 = m.isbn = isbn
                break
            if len(isbn) == 10 and not m.isbn:
                m.isbn = isbn
        langs = doc.get("language") or []
        m.language = langs[0] if langs else ""
        out.append(m)
    return out


def _google_search(query: str) -> list[BookMetadata]:
    params = {"q": query, "maxResults": 10}
    if Config.GOOGLE_BOOKS_API_KEY:
        params["key"] = Config.GOOGLE_BOOKS_API_KEY
    try:
        r = requests.get(GOOGLE_BOOKS_SEARCH, params=params, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        items = r.json().get("items") or []
    except (requests.RequestException, ValueError):
        return []
    out = []
    for item in items:
        vi = item.get("volumeInfo") or {}
        m = BookMetadata(source="Google Books")
        m.title = vi.get("title", "")
        if vi.get("subtitle"):
            m.title = f"{m.title}: {vi['subtitle']}"
        m.title_sort = title_sort_key(m.title)
        m.author = ", ".join((vi.get("authors") or [])[:3])
        m.author_sort = author_sort_key(m.author)
        date = vi.get("publishedDate", "")
        m.year = date[:4] if date else ""
        m.publisher = vi.get("publisher", "")
        for idb in vi.get("industryIdentifiers") or []:
            if idb.get("type") == "ISBN_13":
                m.isbn13 = m.isbn = idb["identifier"]
            elif idb.get("type") == "ISBN_10" and not m.isbn:
                m.isbn = idb["identifier"]
        m.language = vi.get("language", "")
        out.append(m)
    return out


def _isbn_lookup(isbn: str) -> BookMetadata | None:
    params = {"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"}
    try:
        r = requests.get(OPEN_LIBRARY_ISBN, params=params, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    book = data.get(f"ISBN:{isbn}")
    if not book:
        return None
    m = BookMetadata(source="Open Library (ISBN)")
    m.title = book.get("title", "")
    m.title_sort = title_sort_key(m.title)
    authors = book.get("authors") or []
    m.author = ", ".join(normalise_author(a.get("name", "")) for a in authors[:3])
    m.author_sort = author_sort_key(m.author)
    pub_date = book.get("publish_date", "")
    m.year = pub_date[:4] if pub_date else ""
    pubs = book.get("publishers") or []
    m.publisher = pubs[0].get("name", "") if pubs else ""
    places = book.get("publish_places") or []
    m.city = places[0].get("name", "") if places else ""
    m.isbn = isbn
    if len(isbn) == 13:
        m.isbn13 = isbn
    return m


def search_books(query: str) -> list[BookMetadata]:
    """Search by free text or a bare ISBN; returns up to 15 deduped results."""
    clean_q = _clean_isbn(query)
    if re.fullmatch(r"\d{10}|\d{13}", clean_q):
        hit = _isbn_lookup(clean_q)
        if hit:
            return [hit]
    combined = _ol_search(query) + _google_search(query)
    seen, deduped = set(), []
    for r in combined:
        key = re.sub(r"\W+", "", r.title.lower())[:25]
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped[:15]
