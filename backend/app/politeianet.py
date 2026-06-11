"""
Politeianet (politeianet.gr) client — a premium Greek bookshop whose bibliographic
metadata is exceptionally rich (often better than BiblioNet for Greek titles).

Two stages:
  1. SEARCH — free-text/ISBN search is served by the site's Findbar widget
     (https://app.findbar.io/search/politeianet.gr/full?query=…), which returns an
     HTML fragment of result cards linking to product pages. We pull the product
     "slugs" (the last path segment of /el/products/<slug>) out of that HTML.
  2. DETAIL — each slug is resolved to a FULL clean record through the site's public
     Bizweb API (https://politeia-api.extend.gr/v1/products/getbyurl?url=<slug>):
     title, description, ISBN, pages, year, cover image and contributors
     (author / editor / publisher), all UTF-8-clean at source.

Candidates are returned in the same shape every other Find-match / Enrich provider
uses. Every entry point degrades to [] / None on any failure and never raises — note
the Findbar search edge returns HTTP 403 to datacenter IPs, so in such environments
search yields nothing while the (directly reachable) detail API still works.
"""
from __future__ import annotations

import re

import requests

from .config import Config
from .encoding import normalize_text

_FINDBAR = "https://app.findbar.io/search/politeianet.gr/full"
_API = "https://politeia-api.extend.gr/v1"
_SITE = "https://www.politeianet.gr"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Origin": _SITE, "Referer": _SITE + "/",
            "Accept-Language": "el,en;q=0.9"}

# product slug = last segment of /el/products/<slug> or /products/<slug>
_SLUG_RE = re.compile(r"/(?:[a-z]{2}/)?products/([A-Za-z0-9][^\"'?#<>\s]*)")
_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"(1[4-9]\d{2}|20\d{2})")


def _digits(s) -> str:
    return re.sub(r"[^0-9Xx]", "", str(s or ""))


def _search_slugs(query: str, limit: int = 12, timeout: float | None = None) -> list[str]:
    """Findbar full-search → ordered, de-duplicated product slugs (best-effort)."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return []
    try:
        r = requests.get(_FINDBAR, params={"query": q},
                         headers=_HEADERS, timeout=timeout or Config.HTTP_TIMEOUT)
        if r.status_code != 200:
            return []
        html = r.text
    except requests.RequestException:
        return []
    out, seen = [], set()
    for slug in _SLUG_RE.findall(html):
        slug = slug.rstrip("/")
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
        if len(out) >= limit:
            break
    return out


def _author_name(c: dict) -> str:
    name = (c.get("contributorName") or "").strip()
    surname = (c.get("contributorSurname") or "").strip()
    full = f"{name} {surname}".strip()
    if not full:
        full = (c.get("comb_name") or c.get("d_name") or "").split(" - ")[0].strip()
    full = re.sub(r"\s*\([^)]*\)", "", full)        # drop "(NOBEL 1998)" award notes
    return re.sub(r"\s+", " ", full).strip()


def _by_role(rec: dict, role: str) -> list[str]:
    out = []
    for c in (rec.get("contributors") or []):
        if isinstance(c, dict) and c.get("contributorCategoryCode") == role:
            nm = _author_name(c)
            if nm:
                out.append(nm)
    return out


def _normalise(rec: dict) -> dict:
    desc = rec.get("md") or rec.get("dsm") or rec.get("smry")
    if desc:
        desc = _TAG_RE.sub("", str(desc)).strip()
        if len(desc) < 3:        # "-" / "." placeholders carry no information
            desc = None
    year = None
    for key in ("year", "release", "publish_date", "cdt"):
        m = _YEAR_RE.search(str(rec.get(key) or ""))
        if m:
            year = m.group(1)
            break
    pubs = _by_role(rec, "publisher")
    return {
        "title": normalize_text(rec.get("nm") or rec.get("mt")) or None,
        "subtitle": normalize_text(rec.get("sub_title")) or None,
        "authors": [normalize_text(a) for a in _by_role(rec, "author")][:5],
        "publisher": normalize_text(pubs[0]) if pubs else None,
        "published_date": year,
        "pages": str(rec.get("pieces") or "") or None,
        "description": normalize_text(desc) or None,
        "language": None,
        "isbn": _digits(rec.get("bc")) or None,
        "cover_url": (rec.get("img1") or "").strip() or None,
        "source": "politeianet",
    }


def _detail(slug: str, timeout: float | None = None) -> dict | None:
    """Resolve a product slug to its full record via the public Bizweb API."""
    if not slug:
        return None
    try:
        r = requests.get(_API + "/products/getbyurl", params={"url": slug},
                         headers=_HEADERS, timeout=timeout or Config.HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        rec = r.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(rec, dict) or not (rec.get("nm") or rec.get("mt")):
        return None
    return _normalise(rec)


def search_titles(query: str, limit: int = 12, timeout: float | None = None) -> list[dict]:
    """Free-text title/author search → candidate records (for the Find-match picker)."""
    out = []
    for slug in _search_slugs(query, limit=limit, timeout=timeout):
        rec = _detail(slug, timeout=timeout)
        if rec and rec.get("title"):
            out.append(rec)
    return out


def lookup_isbn(isbn: str, timeout: float | None = None) -> dict | None:
    """Search by ISBN and return the matching product's metadata (for Enrich)."""
    want = _digits(isbn)
    if not want:
        return None
    for slug in _search_slugs(want, limit=8, timeout=timeout):
        # the slug usually starts with the ISBN, but always confirm against the record
        rec = _detail(slug, timeout=timeout)
        if rec and rec.get("isbn") and want in (rec["isbn"], _digits(rec["isbn"])):
            return rec
    return None
