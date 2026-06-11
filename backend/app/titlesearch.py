"""
Multi-source title/author search for the "Find match" picker (no-ISBN books).

Each provider returns candidates in one shape so the picker + enrichment.apply_candidate
treat them uniformly:
  {title, subtitle, authors[list], published_date, pages, description, isbn, cover_url, source}

Providers degrade to [] on any error (network, blocking, parse) — never raise.
Amazon has no free search API; we best-effort parse the public results page, which
Amazon frequently blocks for non-browser clients, so it may return nothing.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

import requests

from .config import Config
from . import biblionet
from . import politeianet

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _politeianet(query: str) -> list[dict]:
    return politeianet.search_titles(query, limit=12)


def _biblionet(query: str) -> list[dict]:
    return biblionet.search_titles(query, limit=12)


def _openlibrary(query: str) -> list[dict]:
    params = {"q": query, "limit": 10,
              "fields": "title,subtitle,author_name,first_publish_year,isbn,cover_i,number_of_pages_median"}
    try:
        r = requests.get("https://openlibrary.org/search.json", params=params, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        docs = r.json().get("docs", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for d in docs:
        cover_i = d.get("cover_i")
        isbns = d.get("isbn") or []
        isbn13 = next((x for x in isbns if len(x) == 13), (isbns[0] if isbns else None))
        out.append({
            "title": d.get("title"), "subtitle": d.get("subtitle"),
            "authors": (d.get("author_name") or [])[:5],
            "published_date": str(d.get("first_publish_year") or "") or None,
            "pages": str(d.get("number_of_pages_median") or "") or None,
            "description": None, "isbn": isbn13,
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i else None,
            "source": "openlibrary",
        })
    return out


def _google(query: str) -> list[dict]:
    params = {"q": query, "maxResults": 10}
    if Config.GOOGLE_BOOKS_API_KEY:
        params["key"] = Config.GOOGLE_BOOKS_API_KEY
    try:
        r = requests.get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=Config.HTTP_TIMEOUT)
        r.raise_for_status()
        items = r.json().get("items") or []
    except (requests.RequestException, ValueError):
        return []
    out = []
    for it in items:
        vi = it.get("volumeInfo") or {}
        isbn = None
        for idb in vi.get("industryIdentifiers") or []:
            if idb.get("type") == "ISBN_13":
                isbn = idb["identifier"]
        img = (vi.get("imageLinks") or {}).get("thumbnail")
        if img:
            img = img.replace("http://", "https://")
        out.append({
            "title": vi.get("title"), "subtitle": vi.get("subtitle"),
            "authors": (vi.get("authors") or [])[:5],
            "published_date": vi.get("publishedDate") or None,
            "pages": str(vi.get("pageCount") or "") or None,
            "description": vi.get("description"), "isbn": isbn,
            "cover_url": img, "source": "google",
        })
    return out


def _amazon(query: str) -> list[dict]:
    """Best-effort parse of amazon.com book search. Often blocked → returns []."""
    url = "https://www.amazon.com/s?" + urllib.parse.urlencode({"k": query, "i": "stripbooks"})
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=Config.HTTP_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return []
    out, seen = [], set()
    for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', html):
        asin = m.group(1)
        if asin in seen:
            continue
        seg = html[m.start():m.start() + 6000]
        if "s-search-result" not in seg:
            continue
        tm = re.search(r"<h2[^>]*>.*?<span[^>]*>([^<]{3,})</span>", seg, re.S)
        im = re.search(r'(https://m\.media-amazon\.com/images/I/[^"\s]+?\.(?:jpg|png))', seg)
        if not tm:
            continue
        seen.add(asin)
        out.append({
            "title": re.sub(r"\s+", " ", tm.group(1)).strip(), "subtitle": None,
            "authors": [], "published_date": None, "pages": None, "description": None,
            "isbn": asin if asin.isdigit() else None,   # 10-digit ASINs are ISBN-10s
            "cover_url": im.group(1) if im else None, "source": "amazon",
        })
        if len(out) >= 12:
            break
    return out


# Pre-coded national-library catalogues live in sru.LIBRARIES (title + ISBN templates),
# reused by both Find match (here, title query) and Enrich (lookup.py, ISBN query).
# British Library and the Greek NLG are intentionally absent: BL has no open SRU (services
# impaired since its 2023 cyber-incident; the Jisc union is Cloudflare-gated), and the Greek
# NLG exposes no public SRU. Add either via Admin → Custom catalogue sources if a working
# endpoint appears. BiblioNet already covers Greek.
def _sru_provider(name, url):
    def f(query):
        from . import sru
        rows = sru.search(url, query) or []
        for r in rows:
            r["source"] = name
        return rows
    return f


def _builtin_sru_providers():
    from . import sru
    return {k: (lib["name"], _sru_provider(lib["name"], lib["title"]))
            for k, lib in sru.LIBRARIES.items()}


# key -> (display name, provider). Order = display order.
PROVIDERS = {
    "politeianet": ("Politeianet (Greek)", _politeianet),
    "biblionet": ("BiblioNet (Greek)", _biblionet),
    **_builtin_sru_providers(),                 # loc, dnb
    "google": ("Google Books", _google),
    "openlibrary": ("OpenLibrary", _openlibrary),
    "amazon": ("Amazon.com", _amazon),
}


def _custom_sources() -> list[dict]:
    """User-added SRU catalogues (Admin → Custom catalogue sources). [{key,name,url}]."""
    from .settings import get_setting
    return [s for s in (get_setting("custom_sources") or [])
            if s.get("key") and s.get("name") and s.get("url")]


def available() -> list[dict]:
    builtin = [{"key": k, "name": name} for k, (name, _) in PROVIDERS.items()]
    custom = [{"key": "custom:" + s["key"], "name": s["name"], "custom": True}
              for s in _custom_sources()]
    return builtin + custom


def search(sources, query: str) -> list[dict]:
    """Search the selected sources (built-in + user SRU catalogues); merged + source-tagged."""
    keys = list(sources or []) or ["biblionet"]
    cmap = {"custom:" + s["key"]: s for s in _custom_sources()}
    out = []
    for key in keys:
        try:
            if key in PROVIDERS:
                out.extend(PROVIDERS[key][1](query) or [])
            elif key in cmap:
                from . import sru
                rows = sru.search(cmap[key]["url"], query) or []
                for r in rows:
                    r["source"] = cmap[key]["name"]
                out.extend(rows)
        except Exception:
            continue
    return [c for c in out if c.get("title")]
