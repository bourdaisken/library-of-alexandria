"""
"E-book Metadata Quality" — a self-contained e-book metadata + rename tool.

Renames e-book/comic files on disk to a configurable bibliographic standard, using
embedded metadata (ebookmeta) + optional online search (booksearch). Endpoints mirror
the embedded tool so its UI works unchanged under the /api/bookren prefix.

Writes are gated to admins (the blueprint's before_request: POSTs need a write role).
Renaming a file that's already cataloged auto-updates the stored Copy.file_ref so the
catalog never points at a stale path. All file access is constrained to the allowed
roots (browse.allowed_roots) so it can't escape the mounted media tree.
"""
from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

from flask import Blueprint, jsonify, request

from .auth import require_auth
from .db import Session
from . import models as m
from .ebookmeta import BookMetadata, extract_file_metadata, scan_directory
from .renamer import DEFAULT_TEMPLATE, preview_rename, perform_rename
from .booksearch import search_books
from .browse import list_dir, allowed_roots
from .settings import get_setting, set_setting

bp = Blueprint("bookren", __name__, url_prefix="/api/bookren")

_KNOWN_META_FIELDS = frozenset(f.name for f in dataclasses.fields(BookMetadata)) - {"raw"}

DEFAULT_PRESETS = [
    {"name": "Full bibliographic", "template": DEFAULT_TEMPLATE},
    {"name": "AACR2 / RDA (Library standard)",
     "template": "{author_sort} - {title_sort} - {year} - {publisher}, {city} - {edition} - {format} - ISBN {isbn}"},
    {"name": "Author – Title (Year)", "template": "{author} - {title_sort} ({year})"},
    {"name": "Title only", "template": "{title_sort}"},
    {"name": "ISBN – Title", "template": "{isbn} {title_sort}"},
]

DEFAULT_STRIP_RULES = [
    {"name": "Hash + source tag  (e.g. -- 215d28e7... -- Anna's Archive)",
     "pattern": r"\s*--\s*[0-9a-fA-F]{32,64}\s*--\s*[^.\[\(\-][^\[\(\-]*", "enabled": True},
    {"name": "Bare MD5/SHA hash  (32–64 hex chars)",
     "pattern": r"\b[0-9a-fA-F]{32,64}\b", "enabled": False},
]

_DEFAULT_CONFIG = {
    "template": DEFAULT_TEMPLATE,
    "sort_title": True,
    "auto_search": True,
    "presets": DEFAULT_PRESETS,
    "strip_rules": DEFAULT_STRIP_RULES,
}


@bp.before_request
def _guard():
    return require_auth()   # logged-in; POSTs require an admin (write) role


def _load_config() -> dict:
    cfg = get_setting("bookren_config") or {}
    merged = dict(_DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        merged.update(cfg)
    merged.setdefault("presets", DEFAULT_PRESETS)
    merged.setdefault("strip_rules", DEFAULT_STRIP_RULES)
    return merged


def _meta_from_dict(d: dict) -> BookMetadata:
    clean = {k: (v or "") for k, v in (d or {}).items() if k in _KNOWN_META_FIELDS}
    return BookMetadata(**clean)


def _within_allowed(path: str) -> bool:
    roots = allowed_roots()
    try:
        rp = os.path.realpath(path)
    except OSError:
        return False
    for root in roots:
        try:
            if os.path.commonpath([rp, root]) == root:
                return True
        except ValueError:
            continue
    return False


def _sync_catalog_path(old_path: str, new_path: str) -> int:
    """A file was renamed on disk: re-point any cataloged Copy at its new path."""
    s = Session()
    updated = 0
    for candidate in {old_path, os.path.realpath(old_path)}:
        for c in s.query(m.Copy).filter(m.Copy.file_ref == candidate).all():
            c.file_ref = new_path
            updated += 1
    if updated:
        s.commit()
    return updated


# ── Config ───────────────────────────────────────────────────────────────────
@bp.get("/config")
def get_config():
    return jsonify(_load_config())


@bp.post("/config")
def update_config():
    cfg = _load_config()
    body = request.get_json(silent=True) or {}
    for key in ("template", "sort_title", "auto_search", "presets", "strip_rules"):
        if body.get(key) is not None:
            cfg[key] = body[key]
    set_setting("bookren_config", cfg)
    return jsonify(cfg)


# ── Browse / scan / search ─────────────────────────────────────────────────────
@bp.post("/browse")
def browse():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(list_dir(body.get("path") or None))
    except NotADirectoryError as e:
        return jsonify(error=str(e)), 400


@bp.post("/scan")
def scan():
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    if not path:
        return jsonify(error="no path given"), 400
    if not _within_allowed(path):
        return jsonify(error="path is outside the allowed roots"), 403
    try:
        files = scan_directory(path)
    except NotADirectoryError as e:
        return jsonify(error=str(e)), 400
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    return jsonify(files=files, count=len(files))


@bp.post("/search")
def search():
    body = request.get_json(silent=True) or {}
    q = (body.get("query") or "").strip()
    if not q:
        return jsonify(error="query must not be empty"), 400
    return jsonify(results=[r.to_dict() for r in search_books(q)])


@bp.post("/strip-noise")
def strip_noise():
    body = request.get_json(silent=True) or {}
    stem = body.get("stem") or ""
    cfg = _load_config()
    for rule in cfg.get("strip_rules", []):
        if not rule.get("enabled", True):
            continue
        try:
            stem = re.sub(rule["pattern"], " ", stem, flags=re.IGNORECASE)
        except re.error:
            pass
    for p in (r"\[.*?\]", r"\(.*?\)", r"\bv\d+(\.\d+)?\b",
              r"\b(epub|pdf|mobi|azw3?|djvu|retail|fixed|scan|ocr|hq|z-lib|zlib|libgen)\b",
              r"[-_]{2,}"):
        stem = re.sub(p, " ", stem, flags=re.IGNORECASE)
    stem = stem.replace("_", " ").strip(" -_")
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    return jsonify(cleaned=stem)


# ── Preview / rename ────────────────────────────────────────────────────────────
@bp.post("/preview")
def preview():
    body = request.get_json(silent=True) or {}
    cfg = _load_config()
    template = body.get("template") or cfg["template"]
    try:
        return jsonify(preview_rename(Path(body["file_path"]), template,
                                      _meta_from_dict(body.get("metadata"))))
    except (KeyError, ValueError) as e:
        return jsonify(error=str(e)), 400


@bp.post("/rename")
def rename():
    body = request.get_json(silent=True) or {}
    fp = (body.get("file_path") or "").strip()
    if not fp or not _within_allowed(fp):
        return jsonify(error="path is outside the allowed roots"), 403
    cfg = _load_config()
    template = body.get("template") or cfg["template"]
    dry = bool(body.get("dry_run"))
    try:
        res = perform_rename(Path(fp), template, _meta_from_dict(body.get("metadata")), dry_run=dry)
    except FileNotFoundError as e:
        return jsonify(error=str(e)), 404
    except FileExistsError as e:
        return jsonify(error=str(e)), 409
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if res.get("status") == "renamed":
        res["catalog_synced"] = _sync_catalog_path(res["original"], res["new_path"])
    return jsonify(res)


@bp.post("/rename-batch")
def rename_batch():
    body = request.get_json(silent=True) or {}
    cfg = _load_config()
    dry = bool(body.get("dry_run"))
    results = []
    for item in body.get("renames", []):
        fp = (item.get("file_path") or "").strip()
        template = item.get("template") or cfg["template"]
        if not fp or not _within_allowed(fp):
            results.append({"status": "error", "file_path": fp, "error": "outside allowed roots"})
            continue
        try:
            res = perform_rename(Path(fp), template, _meta_from_dict(item.get("metadata")), dry_run=dry)
            if res.get("status") == "renamed":
                res["catalog_synced"] = _sync_catalog_path(res["original"], res["new_path"])
            results.append(res)
        except (FileNotFoundError, FileExistsError, ValueError) as e:
            results.append({"status": "error", "file_path": fp, "error": str(e)})
    return jsonify(results=results, total=len(results))
