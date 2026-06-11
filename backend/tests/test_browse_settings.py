"""Server-side folder browser + DB settings + rename→catalog auto-sync."""
from app.browse import list_dir
from app.settings import set_setting, get_setting, get_ebooks_dir
from app.bookren import _sync_catalog_path
from app.catalog import add_book
from app import models as m


def test_browse_lists_dirs_and_book_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.epub").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")   # not a book ext → excluded
    res = list_dir(str(tmp_path), roots=[str(tmp_path)])
    assert {d["name"] for d in res["dirs"]} == {"sub"}
    assert {f["name"] for f in res["files"]} == {"a.epub"}


def test_browse_blocks_outside_roots(tmp_path):
    allowed = tmp_path / "allowed"; allowed.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    res = list_dir(str(outside), roots=[str(allowed)])
    # out-of-bounds path → no listing, just the shortcuts (roots) to choose from
    assert res["path"] is None
    assert [s["path"] for s in res["shortcuts"]] == [str(allowed)]


def test_browse_hides_hidden_entries(tmp_path):
    (tmp_path / ".secret").mkdir()
    (tmp_path / "visible").mkdir()
    res = list_dir(str(tmp_path), roots=[str(tmp_path)])
    assert {d["name"] for d in res["dirs"]} == {"visible"}


def test_settings_roundtrip(session):
    set_setting("ebooks_dir", "/data/ebooks")
    assert get_setting("ebooks_dir") == "/data/ebooks"
    assert get_ebooks_dir() == "/data/ebooks"


def test_rename_resyncs_catalog_path(session, tmp_path):
    old = str(tmp_path / "old.epub")
    add_book(session, {"title": "Dune", "authors": ["Frank Herbert"],
                       "copy": {"kind": "ebook", "file_ref": old}})
    new = str(tmp_path / "Dune - Frank Herbert.epub")
    n = _sync_catalog_path(old, new)
    assert n == 1
    copy = session.query(m.Copy).filter(m.Copy.kind == "ebook").one()
    assert copy.file_ref == new
