"""
Embedded-metadata extraction for e-book / comic files.

This is the engine behind the folder-scan e-book importer (see ebookscan.py).
It reads bibliographic metadata out of the files themselves — no external
service, no second container.

Supported formats and their source of truth:
  EPUB                        — Dublin Core via ebooklib
  PDF                         — XMP / info dictionary via pypdf
  DOCX                        — core properties via python-docx
  MOBI/AZW/AZW3/AZW4/PDB/PRC  — EXTH header (pure-Python parser, no dependency)
  FB2                         — FictionBook <description> XML
  CBZ/CBR/CBT                 — embedded ComicInfo.xml (ComicRack)
  DjVu                        — best-effort uncompressed annotation metadata
  ZIP/TAR/TGZ                 — first recognised book file found inside

Every extractor swallows all exceptions and returns an empty BookMetadata on
failure — never raises — so a corrupt file can't crash a scan. Keep that invariant.

Encoding note: callers (ebookscan.py) pass every string through normalize_text()
so the Greek-safe / no-mojibake guarantee holds end to end.
"""
from __future__ import annotations

import os
import re
import struct
import tarfile
import tempfile
import warnings
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

# Articles moved to the end of a title for sort order: "The Silver Chair" -> "Silver Chair, The".
ARTICLES: frozenset[str] = frozenset({"the", "a", "an"})


@dataclass
class BookMetadata:
    """A single book's bibliographic data, normalised across all formats.

    All fields default to "" so callers never need None checks. `raw` holds any
    original payload and is dropped by to_dict()."""
    title: str = ""
    title_sort: str = ""
    author: str = ""
    year: str = ""
    publisher: str = ""
    city: str = ""
    isbn: str = ""            # ISBN-13 preferred, ISBN-10 fallback
    isbn13: str = ""
    series: str = ""
    edition: str = ""
    format: str = ""
    language: str = ""
    author_sort: str = ""
    source: str = ""
    confidence: float = 0.0
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


def title_sort_key(title: str) -> str:
    """Move a leading article to the end: 'The Silver Chair' -> 'Silver Chair, The'."""
    if not title:
        return title
    words = title.split(None, 1)
    if len(words) >= 2 and words[0].lower() in ARTICLES:
        return f"{words[1]}, {words[0]}"
    return title


def normalise_author(name: str) -> str:
    """Convert 'Last, First' to 'First Last' (some sources return inverted names)."""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
    return name


def author_sort_key(name: str) -> str:
    """Convert 'First Last' to 'Last, First' for AACR2/RDA filing (first author only).

    Known limitation: compound/particled surnames (van, von, de, García Márquez) are
    not handled specially — the last word is treated as the surname."""
    if not name:
        return name
    if ", " in name:
        parts = name.split(", ", 1)
        if " " not in parts[0]:
            return name  # already inverted
    authors = [a.strip() for a in name.replace(" and ", ", ").split(", ")]
    if not authors:
        return name
    words = authors[0].split()
    if len(words) < 2:
        return name
    inverted = f"{words[-1]}, {' '.join(words[:-1])}"
    if len(authors) > 1:
        return inverted + ", " + ", ".join(authors[1:])
    return inverted


# ── Constants ──────────────────────────────────────────────────────────────────

BOOK_EXTENSIONS: frozenset[str] = frozenset({
    ".epub", ".pdf", ".docx", ".doc",
    ".mobi", ".azw", ".azw3", ".azw4", ".pdb", ".prc",
    ".fb2",
    ".djvu", ".djv",
    ".cbz", ".cbr", ".cbt",   # comic archives
    ".zip", ".tar", ".tgz",   # generic archives (books are sometimes zipped)
})

_ARCHIVE_EXTS: frozenset[str] = frozenset({
    ".zip", ".tar", ".tgz", ".cbz", ".cbr", ".cbt",
})
_INNER_BOOK_EXTS: frozenset[str] = BOOK_EXTENSIONS - _ARCHIVE_EXTS

# Refuse to extract an archive member larger than this (guards against zip bombs).
_MAX_MEMBER_BYTES = 200 * 1024 * 1024  # 200 MiB


# ── Per-format extractors ──────────────────────────────────────────────────────


def _extract_epub(path: Path) -> BookMetadata:
    """Read Dublin Core metadata from an EPUB container."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # ebooklib deprecation noise
            from ebooklib import epub

            book = epub.read_epub(str(path), options={"ignore_ncx": True})
            meta = BookMetadata(source="EPUB metadata")

            titles = book.get_metadata("DC", "title")
            meta.title = titles[0][0] if titles else ""
            meta.title_sort = title_sort_key(meta.title) if meta.title else ""

            creators = book.get_metadata("DC", "creator")
            meta.author = ", ".join(c[0] for c in creators[:3]) if creators else ""

            dates = book.get_metadata("DC", "date")
            if dates:
                meta.year = dates[0][0][:4]

            pubs = book.get_metadata("DC", "publisher")
            meta.publisher = pubs[0][0] if pubs else ""

            identifiers = book.get_metadata("DC", "identifier")
            for id_val, id_attrs in identifiers:
                id_clean = re.sub(r"[-\s]", "", id_val)
                if re.fullmatch(r"\d{13}", id_clean):
                    meta.isbn13 = id_clean
                    meta.isbn = id_clean
                    break
                if re.fullmatch(r"\d{10}", id_clean) and not meta.isbn:
                    meta.isbn = id_clean

            langs = book.get_metadata("DC", "language")
            meta.language = langs[0][0] if langs else ""

            return meta
    except Exception:
        return BookMetadata()


def _extract_pdf(path: Path) -> BookMetadata:
    """Read XMP/info metadata from a PDF."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        info = reader.metadata or {}

        meta = BookMetadata(source="PDF metadata")
        meta.title = (info.get("/Title") or "").strip()
        meta.title_sort = title_sort_key(meta.title) if meta.title else ""
        meta.author = (info.get("/Author") or "").strip()

        date_str = info.get("/CreationDate") or ""
        if date_str.startswith("D:") and len(date_str) >= 6:
            meta.year = date_str[2:6]

        meta.publisher = (info.get("/Creator") or "").strip()
        return meta
    except Exception:
        return BookMetadata()


def _extract_docx(path: Path) -> BookMetadata:
    """Read core properties from a DOCX file."""
    try:
        from docx import Document

        doc = Document(str(path))
        props = doc.core_properties
        meta = BookMetadata(source="DOCX metadata")
        meta.title = (props.title or "").strip()
        meta.title_sort = title_sort_key(meta.title) if meta.title else ""
        meta.author = (props.author or "").strip()
        if props.created:
            meta.year = str(props.created.year)
        return meta
    except Exception:
        return BookMetadata()


# ── MOBI / AZW / AZW3 extractor (pure Python — no external dependency) ──────────

_EXTH_AUTHOR    = 100
_EXTH_PUBLISHER = 101
_EXTH_ISBN      = 104
_EXTH_PUBDATE   = 106
_EXTH_TITLE     = 503   # "updated title" — preferred over the PDB full name

_MOBI_CODECS = {1252: "cp1252", 65001: "utf-8"}


def _decode_exth(data: bytes, codec: str) -> str:
    """Decode an EXTH record payload, tolerating the wrong declared codec."""
    for enc in (codec, "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace").strip()


def _parse_exth(rec0: bytes, exth_start: int, codec: str) -> dict[int, str]:
    """Parse the EXTH record block starting at *exth_start* within record 0."""
    fields: dict[int, str] = {}
    if rec0[exth_start:exth_start + 4] != b"EXTH":
        return fields
    record_count = struct.unpack_from(">I", rec0, exth_start + 8)[0]
    pos = exth_start + 12
    for _ in range(record_count):
        if pos + 8 > len(rec0):
            break
        rec_type, rec_len = struct.unpack_from(">II", rec0, pos)
        if rec_len < 8:
            break  # malformed — avoid an infinite loop
        payload = rec0[pos + 8: pos + rec_len]
        if rec_type not in fields:
            fields[rec_type] = _decode_exth(payload, codec)
        pos += rec_len
    return fields


def _extract_mobi(path: Path) -> BookMetadata:
    """Read EXTH/MOBI-header metadata from a MOBI, AZW, or AZW3 file."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(262_144)

        if len(head) < 78 + 8:
            return BookMetadata()
        num_records = struct.unpack_from(">H", head, 76)[0]
        if num_records < 1:
            return BookMetadata()
        rec0_offset = struct.unpack_from(">I", head, 78)[0]
        rec0_end = (
            struct.unpack_from(">I", head, 78 + 8)[0]
            if num_records > 1 else len(head)
        )
        rec0 = head[rec0_offset:rec0_end]

        if rec0[16:20] != b"MOBI":
            return BookMetadata()   # not a MOBI-family file

        mobi_off = 16
        mobi_len = struct.unpack_from(">I", rec0, mobi_off + 4)[0]
        encoding_code = struct.unpack_from(">I", rec0, mobi_off + 12)[0]
        codec = _MOBI_CODECS.get(encoding_code, "utf-8")

        fullname_off = struct.unpack_from(">I", rec0, mobi_off + 0x54)[0]
        fullname_len = struct.unpack_from(">I", rec0, mobi_off + 0x58)[0]
        full_name = ""
        if 0 < fullname_len and fullname_off + fullname_len <= len(rec0):
            full_name = _decode_exth(
                rec0[fullname_off: fullname_off + fullname_len], codec
            )

        exth_flags = struct.unpack_from(">I", rec0, mobi_off + 0x70)[0]
        exth_fields: dict[int, str] = {}
        if exth_flags & 0x40:
            exth_fields = _parse_exth(rec0, mobi_off + mobi_len, codec)

        meta = BookMetadata(source="MOBI metadata")
        meta.title = exth_fields.get(_EXTH_TITLE) or full_name
        meta.title_sort = title_sort_key(meta.title) if meta.title else ""
        meta.author = exth_fields.get(_EXTH_AUTHOR, "")
        meta.publisher = exth_fields.get(_EXTH_PUBLISHER, "")

        pub_date = exth_fields.get(_EXTH_PUBDATE, "")
        mt = re.search(r"\d{4}", pub_date)
        if mt:
            meta.year = mt.group(0)

        isbn_clean = re.sub(r"[-\s]", "", exth_fields.get(_EXTH_ISBN, ""))
        if re.fullmatch(r"\d{13}", isbn_clean):
            meta.isbn13 = isbn_clean
            meta.isbn = isbn_clean
        elif re.fullmatch(r"\d{10}", isbn_clean):
            meta.isbn = isbn_clean

        return meta
    except Exception:
        return BookMetadata()


# ── FB2 (FictionBook XML) extractor ─────────────────────────────────────────────


def _local(tag: str) -> str:
    """Return an XML tag's local name, discarding any {namespace} prefix."""
    return tag.rsplit("}", 1)[-1].lower()


def _find_local(parent, *names):
    wanted = {n.lower() for n in names}
    for el in parent.iter():
        if _local(el.tag) in wanted:
            return el
    return None


def _fb2_author_name(author_el) -> str:
    parts = []
    for key in ("first-name", "middle-name", "last-name"):
        el = next((c for c in author_el.iter() if _local(c.tag) == key), None)
        if el is not None and el.text and el.text.strip():
            parts.append(el.text.strip())
    if parts:
        return " ".join(parts)
    nick = next((c for c in author_el.iter() if _local(c.tag) == "nickname"), None)
    return nick.text.strip() if nick is not None and nick.text else ""


def _extract_fb2_bytes(data: bytes) -> BookMetadata:
    """Parse FB2 metadata from raw bytes (shared by file and archive paths)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return BookMetadata()

    desc = _find_local(root, "description")
    if desc is None:
        return BookMetadata()

    meta = BookMetadata(source="FB2 metadata")

    title_info = _find_local(desc, "title-info")
    publish_info = _find_local(desc, "publish-info")

    if title_info is not None:
        bt = next((c for c in title_info.iter()
                   if _local(c.tag) == "book-title"), None)
        if bt is not None and bt.text:
            meta.title = bt.text.strip()

        authors = [a for a in title_info.iter() if _local(a.tag) == "author"]
        names = [n for n in (_fb2_author_name(a) for a in authors[:3]) if n]
        meta.author = ", ".join(names)

        seq = next((c for c in title_info.iter()
                    if _local(c.tag) == "sequence"), None)
        if seq is not None:
            meta.series = (seq.get("name") or "").strip()

        lang = next((c for c in title_info.iter() if _local(c.tag) == "lang"), None)
        if lang is not None and lang.text:
            meta.language = lang.text.strip()

        date = next((c for c in title_info.iter() if _local(c.tag) == "date"), None)
        if date is not None:
            raw = (date.get("value") or date.text or "")
            mt = re.search(r"\d{4}", raw)
            if mt:
                meta.year = mt.group(0)

    if publish_info is not None:
        pub = next((c for c in publish_info.iter()
                    if _local(c.tag) == "publisher"), None)
        if pub is not None and pub.text:
            meta.publisher = pub.text.strip()

        city = next((c for c in publish_info.iter()
                     if _local(c.tag) == "city"), None)
        if city is not None and city.text:
            meta.city = city.text.strip()

        yr = next((c for c in publish_info.iter() if _local(c.tag) == "year"), None)
        if yr is not None and yr.text:
            mt = re.search(r"\d{4}", yr.text)
            if mt:
                meta.year = mt.group(0)

        isbn = next((c for c in publish_info.iter()
                     if _local(c.tag) == "isbn"), None)
        if isbn is not None and isbn.text:
            clean = re.sub(r"[-\s]", "", isbn.text)
            if re.fullmatch(r"\d{13}", clean):
                meta.isbn13 = clean
                meta.isbn = clean
            elif re.fullmatch(r"\d{10}", clean):
                meta.isbn = clean

    meta.title_sort = title_sort_key(meta.title) if meta.title else ""
    return meta


def _extract_fb2(path: Path) -> BookMetadata:
    try:
        return _extract_fb2_bytes(path.read_bytes())
    except Exception:
        return BookMetadata()


# ── Comic archive (CBZ / CBR / CBT) extractor ───────────────────────────────────


def _parse_comic_info(data: bytes) -> BookMetadata:
    """Parse a ComicInfo.xml payload into BookMetadata."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return BookMetadata()

    def text(name: str) -> str:
        el = next((c for c in root.iter() if _local(c.tag) == name.lower()), None)
        return el.text.strip() if el is not None and el.text else ""

    meta = BookMetadata(source="ComicInfo.xml")
    series = text("series")
    number = text("number")
    title = text("title")

    if title:
        meta.title = title
    elif series and number:
        meta.title = f"{series} #{number}"
    elif series:
        meta.title = series

    meta.series = series
    meta.author = text("writer") or text("penciller")
    meta.publisher = text("publisher")

    year = text("year")
    if re.fullmatch(r"\d{4}", year):
        meta.year = year

    lang = text("languageiso")
    if lang:
        meta.language = lang

    gtin = re.sub(r"[-\s]", "", text("gtin"))
    if re.fullmatch(r"\d{13}", gtin):
        meta.isbn13 = gtin
        meta.isbn = gtin

    meta.title_sort = title_sort_key(meta.title) if meta.title else ""
    return meta


def _comic_info_from_zip(path: Path) -> BookMetadata | None:
    """Return ComicInfo metadata from a ZIP-based comic, or None if not a ZIP."""
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if os.path.basename(name).lower() == "comicinfo.xml":
                    return _parse_comic_info(zf.read(name))
    except Exception:
        return BookMetadata()
    return BookMetadata(source="ComicInfo.xml")  # ZIP but no ComicInfo → empty-ish


def _extract_comic(path: Path) -> BookMetadata:
    """Read ComicInfo.xml from a .cbz / .cbr / .cbt comic archive."""
    try:
        zres = _comic_info_from_zip(path)
        if zres is not None and zres.title:
            return zres

        if tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as tf:
                for member in tf.getmembers():
                    if (member.isfile()
                            and os.path.basename(member.name).lower() == "comicinfo.xml"):
                        fh = tf.extractfile(member)
                        if fh is not None:
                            return _parse_comic_info(fh.read())

        try:
            import rarfile  # optional dependency
            if rarfile.is_rarfile(str(path)):
                with rarfile.RarFile(str(path)) as rf:
                    for name in rf.namelist():
                        if os.path.basename(name).lower() == "comicinfo.xml":
                            return _parse_comic_info(rf.read(name))
        except ImportError:
            pass  # rarfile not installed — real .cbr stays unread, no crash

        return BookMetadata()
    except Exception:
        return BookMetadata()


# ── DjVu extractor (best effort) ────────────────────────────────────────────────


def _extract_djvu(path: Path) -> BookMetadata:
    """Best-effort scan for an uncompressed DjVu metadata annotation."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4 * 1024 * 1024)
        if not head.startswith(b"AT&T") and b"DJV" not in head[:64]:
            return BookMetadata()

        text = head.decode("latin-1", errors="ignore")
        idx = text.find("(metadata")
        if idx < 0:
            return BookMetadata()
        window = text[idx: idx + 4096]
        pairs = re.findall(r'\(\s*"?([^"\s()]+)"?\s+"([^"]*)"\s*\)', window)
        pairs = {k.lower(): v.strip() for k, v in pairs}

        meta = BookMetadata(source="DjVu metadata")
        meta.title = pairs.get("title", "")
        meta.author = pairs.get("author", "") or pairs.get("creator", "")
        meta.publisher = pairs.get("publisher", "")
        mt = re.search(r"\d{4}", pairs.get("year", "") or pairs.get("date", ""))
        if mt:
            meta.year = mt.group(0)
        isbn = re.sub(r"[-\s]", "", pairs.get("isbn", ""))
        if re.fullmatch(r"\d{13}", isbn):
            meta.isbn13 = isbn
            meta.isbn = isbn
        elif re.fullmatch(r"\d{10}", isbn):
            meta.isbn = isbn
        meta.title_sort = title_sort_key(meta.title) if meta.title else ""
        return meta if (meta.title or meta.author) else BookMetadata()
    except Exception:
        return BookMetadata()


# ── Archive extractor (ZIP / TAR / TGZ) ─────────────────────────────────────────


def _extract_from_member_bytes(data: bytes, ext: str) -> BookMetadata:
    """Write *data* to a temp file with suffix *ext* and run the extractor on it."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return extract_file_metadata(Path(tmp_path))
    except Exception:
        return BookMetadata()
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _extract_archive(path: Path) -> BookMetadata:
    """Extract metadata from the first recognised book file inside an archive."""
    try:
        members: list[tuple[str, int]] = []
        comic_info_member: str | None = None
        kind = None

        if zipfile.is_zipfile(path):
            kind = "zip"
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    base = os.path.basename(info.filename).lower()
                    if base == "comicinfo.xml":
                        comic_info_member = info.filename
                    members.append((info.filename, info.file_size))
        elif tarfile.is_tarfile(path):
            kind = "tar"
            with tarfile.open(path, "r:*") as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    base = os.path.basename(member.name).lower()
                    if base == "comicinfo.xml":
                        comic_info_member = member.name
                    members.append((member.name, member.size))
        else:
            return BookMetadata()

        book_members = [
            (name, size) for name, size in members
            if Path(name).suffix.lower() in _INNER_BOOK_EXTS
            and 0 < size <= _MAX_MEMBER_BYTES
        ]
        book_members.sort(key=lambda t: t[1], reverse=True)

        def _read(name: str) -> bytes:
            if kind == "zip":
                with zipfile.ZipFile(path) as zf:
                    return zf.read(name)
            with tarfile.open(path, "r:*") as tf:
                fh = tf.extractfile(name)
                return fh.read() if fh is not None else b""

        for name, _size in book_members:
            ext = Path(name).suffix.lower()
            data = _read(name)
            if ext == ".fb2":
                meta = _extract_fb2_bytes(data)
            else:
                meta = _extract_from_member_bytes(data, ext)
            if meta.title or meta.author:
                return meta

        if comic_info_member is not None:
            return _parse_comic_info(_read(comic_info_member))

        return BookMetadata()
    except Exception:
        return BookMetadata()


# ── Public interface ───────────────────────────────────────────────────────────


def extract_file_metadata(path: Path) -> BookMetadata:
    """Extract embedded bibliographic metadata from *path*; never raises."""
    ext = path.suffix.lower()
    if ext == ".epub":
        return _extract_epub(path)
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in (".docx", ".doc"):
        return _extract_docx(path)
    if ext in (".mobi", ".azw", ".azw3", ".azw4", ".pdb", ".prc"):
        return _extract_mobi(path)
    if ext == ".fb2":
        return _extract_fb2(path)
    if ext in (".cbz", ".cbr", ".cbt"):
        return _extract_comic(path)
    if ext in (".djvu", ".djv"):
        return _extract_djvu(path)
    if ext in (".zip", ".tar", ".tgz"):
        return _extract_archive(path)
    return BookMetadata()


def scan_directory(root: str | Path) -> list[dict]:
    """Walk *root* recursively and return a list of book-file descriptor dicts.

    Each dict has: path, name, stem, ext, size, rel_path, embedded (a
    BookMetadata.to_dict() if a title was read, else None).

    Uses expanduser() (not resolve()) on purpose — resolve() follows symlinks and
    breaks on VeraCrypt / FUSE / network mounts. Hidden dirs/files are skipped;
    unreadable files are skipped rather than raising.
    """
    root = Path(root).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    files: list[dict] = []
    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            fpath = Path(dirpath_str) / fname
            ext = fpath.suffix.lower()
            if ext not in BOOK_EXTENSIONS:
                continue
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            try:
                rel = str(fpath.relative_to(root))
            except ValueError:
                rel = str(fpath)
            embedded = extract_file_metadata(fpath)
            files.append({
                "path": str(fpath),
                "name": fpath.name,
                "stem": fpath.stem,
                "ext": ext,
                "size": size,
                "rel_path": rel,
                "embedded": embedded.to_dict() if embedded.title else None,
            })
    return files
