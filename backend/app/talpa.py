"""
LibraryThing TALPA — natural-language "describe a book" discovery search.

Unlike the rest of librarything.com (Cloudflare-blocked server-side), the TALPA
API endpoint is reachable. You pass a free-text description and it returns ranked
candidate works (title + LibraryThing work_id + ISBNs). We cross-link those ISBNs
to your catalog (owned?) and to OpenLibrary covers in the UI.

The dev token has a SMALL daily quota (50 requests) — use sparingly. Never raises;
returns {ok, results, remaining, error}.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .config import Config

_URL = "https://www.librarything.com/api/talpa.php"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def describe(query: str, limit: int = 20, timeout: float = 25.0) -> dict:
    """Natural-language search → {ok, results:[{title, work_id, isbns[], isbn}], remaining}."""
    token = Config.LIBRARYTHING_TALPA_TOKEN
    if not token:
        return {"ok": False, "error": "TALPA is not configured (set LIBRARYTHING_TALPA_TOKEN).", "results": []}
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "empty query", "results": []}

    params = urllib.parse.urlencode({"token": token, "search": q, "limit": limit})
    try:
        req = urllib.request.Request(f"{_URL}?{params}", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {"ok": False, "error": "TALPA unreachable.", "results": []}

    if isinstance(data, dict) and data.get("error"):
        return {"ok": False, "error": data["error"].get("wording", "TALPA error"), "results": []}

    resp = data.get("response", {}) if isinstance(data, dict) else {}
    out = []
    for r in resp.get("resultlist", []):
        isbns = [i for i in (r.get("isbns") or []) if i]
        out.append({
            "title": r.get("title"),
            "work_id": r.get("work_id"),
            "isbns": isbns,
            "isbn": next((i for i in isbns if len(i) == 13), (isbns[0] if isbns else None)),
        })
    remaining = ((data.get("request", {}) or {}).get("developer", {}) or {}).get("remaining")
    return {"ok": True, "results": out, "remaining": remaining}
