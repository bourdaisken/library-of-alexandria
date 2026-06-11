"""
Download a cover image and store a COPY of it in the database (so covers are
available offline and are included in pg_dump backups, not just linked).

Used by enrichment when a source (e.g. BiblioNet) returns a cover_url for an
edition that has no cover yet. Sets Edition.cover_path = 'db:<edition_id>'.
"""
from __future__ import annotations

import urllib.request

from . import models as m

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_MAX_BYTES = 8 * 1024 * 1024   # 8 MiB — covers are small; guard against surprises


def store_cover_bytes(s, edition, data: bytes, content_type: str = "image/jpeg",
                      source: str = "upload") -> bool:
    """Store raw image bytes (an uploaded file or a camera photo) as this edition's
    cover. Returns True on success. Sets Edition.cover_path = 'db:<edition_id>'."""
    if not data or len(data) > _MAX_BYTES:
        return False
    ci = s.get(m.CoverImage, edition.id)
    if not ci:
        ci = m.CoverImage(edition_id=edition.id)
        s.add(ci)
    ci.data = data
    ci.content_type = content_type or "image/jpeg"
    ci.source = source
    edition.cover_path = f"db:{edition.id}"
    return True


def store_cover_from_url(s, edition, url: str, source: str = "enrichment",
                         timeout: float = 20.0) -> bool:
    """Fetch *url* and store the bytes as this edition's cover. Returns True on success."""
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content_type = (r.headers.get_content_type() or "image/jpeg")
            data = r.read(_MAX_BYTES + 1)
    except Exception:
        return False
    if not data or len(data) > _MAX_BYTES:
        return False

    ci = s.get(m.CoverImage, edition.id)
    if not ci:
        ci = m.CoverImage(edition_id=edition.id)
        s.add(ci)
    ci.data = data
    ci.content_type = content_type
    ci.source = source
    edition.cover_path = f"db:{edition.id}"
    return True
