"""Filename template engine."""
from pathlib import Path

import pytest

from app.ebookmeta import BookMetadata
from app.renamer import apply_template, preview_rename, perform_rename, DEFAULT_TEMPLATE


def _meta():
    return BookMetadata(title="The Silver Chair", title_sort="Silver Chair, The",
                        author="C. S. Lewis", year="1953", publisher="Bles",
                        isbn13="9780006716686", format="EPUB")


def test_apply_template_fills_and_cleans():
    out = apply_template(DEFAULT_TEMPLATE, _meta())
    assert "Silver Chair, The" in out and "C. S. Lewis" in out and "9780006716686" in out
    assert "/" not in out and "  " not in out  # sanitised, no double spaces


def test_empty_fields_dont_leave_artefacts():
    m = BookMetadata(title="Dune", title_sort="Dune")  # no author/year/isbn
    out = apply_template(DEFAULT_TEMPLATE, m)
    assert out == "Dune"  # dangling separators / "ISBN" label cleaned away


def test_perform_rename_dry_run_and_real(tmp_path):
    f = tmp_path / "ugly_name.epub"
    f.write_bytes(b"x")
    tpl = "{title} - {author}"
    dry = perform_rename(f, tpl, _meta(), dry_run=True)
    assert dry["status"] == "dry_run" and f.exists()  # untouched
    real = perform_rename(f, tpl, _meta(), dry_run=False)
    assert real["status"] == "renamed"
    assert not f.exists()
    assert Path(real["new_path"]).exists()
    assert Path(real["new_path"]).name == "The Silver Chair - C. S. Lewis.epub"


def test_conflict_detected(tmp_path):
    (tmp_path / "The Silver Chair - C. S. Lewis.epub").write_bytes(b"y")
    src = tmp_path / "src.epub"; src.write_bytes(b"z")
    prev = preview_rename(src, "{title} - {author}", _meta())
    assert prev["conflict"] is True
