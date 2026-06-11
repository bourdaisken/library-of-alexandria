"""
App settings store (DB-backed key/value), so things like the e-book folder are
configured in the UI rather than hardcoded in the environment.

Keys:
  ebooks_dir      — absolute path of the e-book folder to scan / browse / rename in
  bookren_config  — template, sort_title, auto_search, presets, strip_rules (the
                    "E-book Metadata Quality" tab's settings; see app/bookren.py)
"""
from __future__ import annotations

import json

from .config import Config
from .db import Session
from . import models as m


def get_setting(key: str, default=None):
    row = Session().get(m.Setting, key)
    if not row or row.value is None:
        return default
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return default


def set_setting(key: str, value) -> None:
    s = Session()
    row = s.get(m.Setting, key)
    if not row:
        row = m.Setting(key=key)
        s.add(row)
    row.value = json.dumps(value, ensure_ascii=False)
    s.commit()


def get_ebooks_dir() -> str:
    """The configured e-book folder: DB setting first, then the env fallback."""
    return (get_setting("ebooks_dir") or Config.EBOOKS_DIR or "").strip()
