"""Folder-scan e-book importer: extraction, cataloging, idempotency, Greek integrity."""
import zipfile

from app.ebookmeta import extract_file_metadata
from app.ebookscan import scan_folder, _isbn_from_name
from app import models as m


def _write_epub(path, title, author, isbn="", language="en", publisher=""):
    """Write a minimal but valid EPUB carrying the given Dublin Core metadata."""
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    ident = f'<dc:identifier id="bookid">{isbn}</dc:identifier>' if isbn else \
            '<dc:identifier id="bookid">urn:uuid:x</dc:identifier>'
    pub = f"<dc:publisher>{publisher}</dc:publisher>" if publisher else ""
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">'
        f"<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>"
        f"{ident}<dc:language>{language}</dc:language>{pub}</metadata>"
        '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="c1"/></spine></package>'
    )
    chapter = '<?xml version="1.0" encoding="utf-8"?><html><body><p>.</p></body></html>'
    with zipfile.ZipFile(path, "w") as z:
        # mimetype must be first and stored uncompressed
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/c1.xhtml", chapter)


def test_extract_epub_reads_metadata(tmp_path):
    p = tmp_path / "book.epub"
    _write_epub(p, "The Silver Chair", "C. S. Lewis", isbn="9780006716686", publisher="Bles")
    meta = extract_file_metadata(p)
    assert meta.title == "The Silver Chair"
    assert meta.author == "C. S. Lewis"
    assert meta.isbn13 == "9780006716686"


def test_scan_catalogs_ebook_copy(session, tmp_path):
    _write_epub(tmp_path / "dune.epub", "Dune", "Frank Herbert", isbn="9780441013593")
    stats = scan_folder(session, root=str(tmp_path))
    assert stats["scanned"] == 1 and stats["added"] == 1 and stats["skipped"] == 0
    work = session.query(m.Work).filter(m.Work.title == "Dune").one()
    copy = work.editions[0].copies[0]
    assert copy.kind == "ebook"
    assert copy.file_ref == str(tmp_path / "dune.epub")
    assert work.editions[0].isbn13 == "9780441013593"


def test_scan_is_idempotent(session, tmp_path):
    _write_epub(tmp_path / "a.epub", "A", "Auth, One", isbn="9780000000001")
    first = scan_folder(session, root=str(tmp_path))
    second = scan_folder(session, root=str(tmp_path))
    assert first["added"] == 1
    assert second["added"] == 0 and second["skipped"] == 1
    assert session.query(m.Copy).filter(m.Copy.kind == "ebook").count() == 1


def test_greek_metadata_intact(session, tmp_path):
    title = "Το Όνομα του Ρόδου"
    author = "Ουμπέρτο Έκο"
    _write_epub(tmp_path / "rosa.epub", title, author, isbn="9789600000001", language="el")
    scan_folder(session, root=str(tmp_path))
    work = session.query(m.Work).filter(m.Work.title == title).one()
    assert work.title == title  # byte-faithful, no mojibake
    a = work.editions[0].copies  # work exists
    assert a
    names = [c.canonical_name for c in
             session.query(m.Author).filter(m.Author.canonical_name == author).all()]
    assert author in names


def test_isbn_from_filename():
    assert _isbn_from_name("Some Book Title 9780140449136 (retail)") == "9780140449136"
    assert _isbn_from_name("nothing here") is None


def test_unparseable_file_cataloged_by_filename(session, tmp_path):
    # A .pdf with garbage bytes: extractor returns empty, so the stem becomes the title.
    (tmp_path / "Mystery Tome.pdf").write_bytes(b"not really a pdf")
    stats = scan_folder(session, root=str(tmp_path))
    assert stats["added"] == 1
    assert session.query(m.Work).filter(m.Work.title == "Mystery Tome").count() == 1
