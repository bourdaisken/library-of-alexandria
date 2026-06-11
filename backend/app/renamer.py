"""
Template-based filename renaming engine.

Used by the "E-book Metadata Quality" tab (app/bookren.py). Substitutes metadata
fields into a filename template, cleans up artefacts left by empty fields, and
performs the on-disk rename (with a dry-run mode for preview).

TEMPLATE PLACEHOLDERS:
    {title} {title_sort} {author} {author_sort} {year} {publisher} {city}
    {isbn} {isbn13} {series} {edition} {format} {language}
{isbn} prefers ISBN-13. Values are sanitised of filename-illegal characters.
"""
from __future__ import annotations

import re
from pathlib import Path

from .ebookmeta import BookMetadata

DEFAULT_TEMPLATE = (
    "{title_sort} - {author} - {year} {publisher}, {city} - {format} - ISBN {isbn}"
)

# Characters illegal in filenames on Windows/macOS/Linux.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r" {2,}")
MAX_STEM_LENGTH = 240


def _sanitise(s: str) -> str:
    return _FORBIDDEN.sub("", s).strip()


def _clean_artefacts(s: str) -> str:
    """Remove punctuation orphaned by empty fields (multi-pass)."""
    for _ in range(3):
        s = re.sub(r",\s*(?= -|$)", "", s)
        s = re.sub(r"( - )+", " - ", s)
        s = re.sub(r"^\s*-\s*", "", s)
        s = re.sub(r"\s*-\s*$", "", s)
        s = re.sub(r"\bISBN\s*(-\s*)?$", "", s)
        s = re.sub(r"\bISBN\s+(-\s+)", "- ", s)
        s = _MULTI_SPACE.sub(" ", s)
        s = s.strip()
    return s


def apply_template(template: str, meta: BookMetadata) -> str:
    """Fill placeholders and return a sanitised filename stem ("" if blank)."""
    replacements = {
        "title":      _sanitise(meta.title),
        "title_sort": _sanitise(meta.title_sort or meta.title),
        "author":     _sanitise(meta.author),
        "year":       _sanitise(meta.year),
        "publisher":  _sanitise(meta.publisher),
        "city":       _sanitise(meta.city),
        "isbn":       _sanitise(meta.isbn13 or meta.isbn),
        "isbn13":     _sanitise(meta.isbn13),
        "series":     _sanitise(meta.series),
        "edition":    _sanitise(meta.edition),
        "format":     _sanitise(meta.format),
        "language":   _sanitise(meta.language),
        "author_sort": _sanitise(meta.author_sort or meta.author),
    }
    result = template
    for key, val in replacements.items():
        result = result.replace(f"{{{key}}}", val)
    result = _clean_artefacts(result)
    if len(result) > MAX_STEM_LENGTH:
        truncated = result[:MAX_STEM_LENGTH]
        last_space = truncated.rfind(" ")
        result = truncated[:last_space].rstrip() if last_space > 0 else truncated
    return result


def build_new_path(original: Path, template: str, meta: BookMetadata) -> Path:
    """Intended new Path after applying template; preserves dir + lowercased extension."""
    stem = apply_template(template, meta)
    if not stem:
        raise ValueError(
            f"Template produced an empty filename for '{original.name}'. "
            "Check that at least one non-empty metadata field is in the template."
        )
    return original.parent / (stem + original.suffix.lower())


def preview_rename(original: Path, template: str, meta: BookMetadata) -> dict:
    """Describe the pending rename WITHOUT performing it."""
    new_path = build_new_path(original, template, meta)
    return {
        "original":      str(original),
        "original_name": original.name,
        "new_name":      new_path.name,
        "new_path":      str(new_path),
        "conflict":      new_path.exists() and new_path.resolve() != original.resolve(),
    }


def perform_rename(original: Path, template: str, meta: BookMetadata, *,
                   dry_run: bool = False) -> dict:
    """Rename *original* per template+meta. Status: renamed | unchanged | dry_run.

    Raises FileNotFoundError / FileExistsError / ValueError on the obvious cases."""
    original = original.resolve()
    if not original.exists():
        raise FileNotFoundError(f"Source file not found: {original}")
    new_path = build_new_path(original, template, meta)
    if new_path.resolve() == original:
        return {"status": "unchanged", "original": str(original),
                "new_path": str(original), "new_name": original.name}
    if new_path.exists():
        raise FileExistsError(f"Target already exists: {new_path}")
    if not dry_run:
        original.rename(new_path)
    return {"status": "dry_run" if dry_run else "renamed", "original": str(original),
            "new_path": str(new_path), "new_name": new_path.name}
