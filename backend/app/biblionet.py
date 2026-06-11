"""
BiblioNet (biblionet.gr) client — the largest Greek-language book catalogue.

Vendored from the user's `biblionet_search.py`: the site's search box is a plain
GET form that renders each result card with a hidden <pre> PHP print_r() dump of
the FULL record (title, summary, ISBNs, pages, publish_date, image_url, …). We
reproduce the request and parse that dump.

Used as an enrichment source (see lookup.py) to fill metadata + covers for Greek
books that OpenLibrary / Google Books don't cover. Stdlib only; never raises out
of `lookup_isbn` (returns None on any failure — the site 500s intermittently).
"""
from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse
import urllib.request

BASE = "https://biblionet.gr"
_ENDPOINT = "/συνθετη-αναζητηση"   # the "books" (titles / ISBN) search
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL)
_KV_RE = re.compile(r"^\[(?P<key>.*?)\]\s*=>\s?(?P<val>.*)$")


def _fetch(query: str, timeout: float = 18.0) -> str | None:
    """Reproduce the homepage search GET; return raw HTML or None on failure."""
    cleaned = re.sub(r"[^\w ]", " ", query or "", flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None
    params = urllib.parse.urlencode({"preselect_filter": "books", "q": cleaned},
                                    quote_via=urllib.parse.quote)
    url = f"{BASE}{urllib.parse.quote(_ENDPOINT)}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except Exception:
        return None


def _parse_print_r(text: str) -> dict:
    """Parse a PHP print_r() dump into nested dicts (tolerant of multi-line values)."""
    lines = html.unescape(text).split("\n")

    def skip_blank(i):
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        return i

    def parse_array(i):
        i = skip_blank(i)
        if i >= len(lines) or lines[i].strip() != "(":
            return {}, i
        i += 1
        out: dict = {}
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped == ")":
                return out, i + 1
            m = _KV_RE.match(stripped)
            if not m:
                i += 1
                continue
            key, val = m.group("key"), m.group("val")
            i += 1
            if val.strip() == "Array":
                child, i = parse_array(i)
                out[key] = child
            else:
                buf = [val]
                while i < len(lines):
                    nxt = lines[i].strip()
                    if nxt == ")" or _KV_RE.match(nxt) or nxt == "":
                        if nxt == "":
                            j = skip_blank(i)
                            if j < len(lines) and (lines[j].strip() == ")" or _KV_RE.match(lines[j].strip())):
                                break
                        else:
                            break
                    buf.append(lines[i])
                    i += 1
                out[key] = "\n".join(buf).strip()
        return out, i

    pos = skip_blank(0)
    if pos < len(lines) and lines[pos].strip() == "Array":
        pos += 1
    result, _ = parse_array(pos)
    return result


def _records(html_text: str):
    """Yield each full print_r record dict that has a title_id."""
    for block in _PRE_RE.findall(html_text):
        if "[title_id]" not in block:
            continue
        rec = _parse_print_r(block)
        if rec.get("title_id"):
            yield rec


def _digits(s: str) -> str:
    return re.sub(r"[^0-9Xx]", "", s or "")


def _year_from(rec: dict) -> str | None:
    """BiblioNet stores publish_date as a Unix timestamp; convert to a 4-digit year."""
    for key in ("publish_date", "first_publish_date"):
        v = (rec.get(key) or "").strip()
        if not v:
            continue
        if v.isdigit() and len(v) >= 9:           # unix timestamp
            try:
                y = dt.datetime.fromtimestamp(int(v), dt.timezone.utc).year
                if 1400 <= y <= 2100:
                    return str(y)
            except (ValueError, OSError, OverflowError):
                pass
        m = re.search(r"(1[4-9]\d{2}|20\d{2})", v)  # or a plain year string
        if m:
            return m.group(1)
    return None


def _names(rec: dict) -> list[str]:
    block = rec.get("contributors")
    if not isinstance(block, dict):
        return []
    out = []
    for entry in block.values():
        if isinstance(entry, dict):
            name = (entry.get("name") or "").strip()
            if name:
                out.append(name)
    return out[:5]


def _normalise(rec: dict) -> dict:
    img = (rec.get("image_url") or "").strip()
    cover = (BASE + img) if img.startswith("/") else (img or None)
    return {
        "title": (rec.get("title") or "").strip() or None,
        "authors": _names(rec),
        "publisher": None,            # the dump carries only publisher_id, not the name
        "published_date": _year_from(rec),
        "pages": (rec.get("pages") or "").strip() or None,
        "description": (rec.get("summary") or "").strip() or None,
        "language": None,   # BiblioNet 'lang' is a numeric code, not a name — don't store it
        "cover_url": cover,
        "source": "biblionet",
    }


def lookup_isbn(isbn: str, timeout: float = 18.0) -> dict | None:
    """Search BiblioNet by ISBN and return the matching record's metadata, or None."""
    want = _digits(isbn)
    if not want:
        return None
    page = _fetch(isbn, timeout=timeout)
    if not page:
        return None
    for rec in _records(page):
        rec_isbns = _digits(rec.get("isbn", "")) + " " + _digits(rec.get("isbn2", "")) + " " + _digits(rec.get("isbn3", ""))
        if want in rec_isbns.split() or want in rec_isbns.replace(" ", ""):
            return _normalise(rec)
    return None


def search_titles(query: str, limit: int = 12, timeout: float = 18.0) -> list[dict]:
    """Free-text title/author search → list of candidate records (for the match picker).

    BiblioNet matches every query word with strict AND, so over-specific queries return
    nothing; the caller lets the user edit the query. Each candidate carries its own ISBN
    and subtitle so the user can tell editions apart."""
    page = _fetch(query, timeout=timeout)
    if not page:
        return []
    out = []
    for rec in _records(page):
        cand = _normalise(rec)
        cand["isbn"] = _digits(rec.get("isbn", ""))
        cand["subtitle"] = (rec.get("subtitle") or "").strip() or None
        cand["title_id"] = (rec.get("title_id") or "").strip()
        out.append(cand)
        if len(out) >= limit:
            break
    return out
