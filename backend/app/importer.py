"""
Offline importer: MASTER CSV -> 3-tier model in Postgres.

No network. Idempotent on Copy.legacy_book_uuid (re-running updates, never duplicates).
Implements an explode -> dedup-upward pipeline:
  each row -> one Copy -> its Edition (dedup by ISBN) -> its Work (dedup by author+title).

The 22 repeated ISBNs collapse to one Edition with multiple Copies (expected).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
import tarfile

from .config import Config
from .db import Session
from .encoding import normalize_text
from . import models as m

_ISBN_PREFIX = re.compile(r"^\s*ISBN[:\s]*", re.I)
_SERIES_POS = re.compile(r"^(?P<name>.*?)(?:\s*\((?P<pos>\d+)\))?\s*$")
_TRUE = {"1", "true", "t", "yes", "y"}
# series_details noise that is not actually a series name
_SERIES_NOISE = {"greek edition", "english edition", "illustrated edition"}


def _norm_isbn(raw: str):
    if not raw:
        return None, None
    s = _ISBN_PREFIX.sub("", raw)
    s = "".join(ch for ch in s if ch.isdigit() or ch in "Xx").upper()
    if len(s) == 13:
        return s, None
    if len(s) == 10:
        return None, s
    return None, None


def _parse_date(raw: str, dayfirst: bool = True):
    """Parse a date. Drops any trailing time, tries D/M or M/D ordering (per `dayfirst`),
    ISO, Excel serials (e.g. 31575 -> 1986), and bare years; rejects implausible years
    (outside 1450..2026). date_published is D/M (dayfirst=True); date_added/read_* are US
    M/D (dayfirst=False). Returns (date|None, year|None)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    datepart = raw.split()[0]                          # drop trailing "HH:MM"
    fmts = (["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y"] if dayfirst
            else ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"]) + ["%Y-%m-%d"]
    for fmt in fmts:
        try:
            d = dt.datetime.strptime(datepart, fmt).date()
            if 1450 <= d.year <= 2026:
                return d, d.year
        except ValueError:
            continue
    if datepart.isdigit():
        n = int(datepart)
        if 15000 <= n <= 60000:                       # Excel serial date (1899-12-30 epoch)
            d = dt.date(1899, 12, 30) + dt.timedelta(days=n)
            if 1450 <= d.year <= 2026:
                return d, d.year
        if 1450 <= n <= 2026:                          # bare year
            return None, n
    for g in re.findall(r"\d{4}", raw):
        if 1450 <= int(g) <= 2026:
            return None, int(g)
    return None, None


def _kind_from_format(fmt: str) -> str:
    f = (fmt or "").lower()
    if any(x in f for x in ("epub", "pdf", "mobi", "azw", "ebook", "kindle")):
        return "ebook"
    if any(x in f for x in ("audio", "cd", "mp3")):
        return "audio"
    return "physical"


def _sort_title(title: str) -> str:
    t = title or ""
    mo = re.match(r"^(A|An|The)\s+(.*)$", t, re.I)
    return f"{mo.group(2)}, {mo.group(1)}" if mo else t


def _sort_name(family_given: str) -> str:
    return family_given.strip()


def _split_authors(raw: str):
    """`Family, Given` joined by `|` (older rows use ` - `). Keep every token verbatim."""
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = raw.split("|") if "|" in raw else raw.split(" - ")
    return [p.strip() for p in parts if p.strip()]


class Importer:
    def __init__(self, session=None, data_dir=None):
        self.s = session or Session()
        self.data_dir = data_dir or Config.DATA_DIR
        self._author_cache: dict[str, m.Author] = {}
        self._series_cache: dict[str, m.Series] = {}
        self._tag_cache: dict[str, m.Tag] = {}
        self.stats = {"rows": 0, "works": 0, "editions": 0, "copies": 0, "covers": 0, "updated": 0}

    # -- get-or-create helpers (dedup) --------------------------------------
    def _get_author(self, sort_name: str) -> m.Author:
        key = sort_name.lower()
        if key in self._author_cache:
            return self._author_cache[key]
        a = self.s.query(m.Author).filter(m.Author.sort_name == sort_name).first()
        if not a:
            a = m.Author(canonical_name=sort_name, sort_name=sort_name)
            a.name_forms.append(m.AuthorNameForm(name_form=sort_name))
            self.s.add(a)
            self.s.flush()
        self._author_cache[key] = a
        return a

    def _get_series(self, name: str) -> m.Series | None:
        if not name:
            return None
        key = name.lower()
        if key in self._series_cache:
            return self._series_cache[key]
        sr = self.s.query(m.Series).filter(m.Series.name == name).first()
        if not sr:
            sr = m.Series(name=name)
            self.s.add(sr)
            self.s.flush()
        self._series_cache[key] = sr
        return sr

    def _get_tag(self, name: str) -> m.Tag:
        key = name.lower()
        if key in self._tag_cache:
            return self._tag_cache[key]
        t = self.s.query(m.Tag).filter(m.Tag.name == name).first()
        if not t:
            t = m.Tag(name=name)
            self.s.add(t)
            self.s.flush()
        self._tag_cache[key] = t
        return t

    def _parse_series(self, raw: str):
        raw = normalize_text((raw or "").strip())
        if not raw:
            return None, None
        first = raw.split("|")[0].strip()
        if first.lower() in _SERIES_NOISE:
            return None, None
        mo = _SERIES_POS.match(first)
        return mo.group("name").strip(), mo.group("pos")

    # -- main ---------------------------------------------------------------
    def import_row(self, row: dict):
        g = lambda k: normalize_text((row.get(k) or "").strip())
        legacy = (row.get("book_uuid") or "").strip()

        # Author tokens (verbatim, all forms). First token = primary author.
        author_tokens = [normalize_text(a) for a in _split_authors(row.get("author_details", ""))]
        primary_sort = _sort_name(author_tokens[0]) if author_tokens else "Unknown"

        title = g("title") or "(untitled)"
        sort_title = _sort_title(title)
        series_name, series_pos = self._parse_series(row.get("series_details", ""))

        # WORK dedup by (primary author sort, normalized title)
        work = (
            self.s.query(m.Work)
            .join(m.WorkContributor, m.WorkContributor.work_id == m.Work.id)
            .join(m.Author, m.Author.id == m.WorkContributor.author_id)
            .filter(m.Work.title == title, m.Author.sort_name == primary_sort)
            .first()
        )
        if not work:
            work = m.Work(title=title, sort_title=sort_title)
            if series_name:
                work.series = self._get_series(series_name)
                work.series_position = series_pos
            self.s.add(work)
            self.s.flush()
            # contributors: primary = author; all distinct tokens become authors w/ name forms
            for i, tok in enumerate(author_tokens):
                au = self._get_author(_sort_name(tok))
                if tok not in [nf.name_form for nf in au.name_forms]:
                    au.name_forms.append(m.AuthorNameForm(name_form=tok))
                exists = any(wc.author_id == au.id for wc in work.contributors)
                if not exists:
                    work.contributors.append(m.WorkContributor(author_id=au.id, role="author"))
            seen_tags = set()
            for gname in [t.strip() for t in (g("genre") or "").split("/") if t.strip()]:
                tag = self._get_tag(gname)
                if tag.id in seen_tags:
                    continue
                seen_tags.add(tag.id)
                work.tags.append(m.WorkTag(tag_id=tag.id))
            self.stats["works"] += 1

        # EDITION dedup by ISBN13 (fallback work+publisher+year+format)
        isbn13, isbn10 = _norm_isbn(row.get("isbn", ""))
        pub = g("publisher") or None
        pdate, pyear = _parse_date(row.get("date_published", ""))
        fmt = g("format") or None
        edition = None
        if isbn13:
            edition = self.s.query(m.Edition).filter(m.Edition.isbn13 == isbn13).first()
        if not edition:
            edition = (
                self.s.query(m.Edition)
                .filter(
                    m.Edition.work_id == work.id,
                    m.Edition.publisher == pub,
                    m.Edition.published_year == pyear,
                    m.Edition.format == fmt,
                )
                .first()
            )
        if not edition:
            pages = row.get("pages", "").strip()
            lp = row.get("list_price", "").strip()
            edition = m.Edition(
                work_id=work.id,
                isbn13=isbn13,
                isbn10=isbn10,
                publisher=pub,
                published_date=pdate,
                published_year=pyear,
                pages=int(pages) if pages.isdigit() else None,
                format=fmt,
                language=g("language") or None,
                list_price=float(lp) if _is_float(lp) else None,
                list_price_currency=Config.DEFAULT_CURRENCY if _is_float(lp) else None,
                description=g("description") or None,
            )
            self.s.add(edition)
            self.s.flush()
            if isbn13:
                edition.identifiers.append(m.EditionIdentifier(scheme="isbn13", value=isbn13))
            if isbn10:
                edition.identifiers.append(m.EditionIdentifier(scheme="isbn10", value=isbn10))
            gr = (row.get("goodreads_book_id") or "").strip()
            if gr and gr != "0":
                edition.identifiers.append(m.EditionIdentifier(scheme="goodreads", value=gr))
            self.stats["editions"] += 1

        # COPY — idempotent on legacy_book_uuid
        copy = None
        if legacy:
            copy = self.s.query(m.Copy).filter(m.Copy.legacy_book_uuid == legacy).first()
        if copy:
            self.stats["updated"] += 1
        else:
            copy = m.Copy(edition_id=edition.id, legacy_book_uuid=legacy or None)
            self.s.add(copy)
            self.stats["copies"] += 1
        copy.kind = _kind_from_format(fmt)
        copy.location = g("bookshelf").rstrip(",").strip() or None     # bookshelf -> physical location
        copy.signed = (row.get("signed", "").strip().lower() in _TRUE)
        adate, _ = _parse_date(row.get("date_added", ""), dayfirst=False)  # date_added is US M/D
        copy.acquired_date = adate
        copy.notes = g("notes") or None                                # provenance + comments
        self.s.flush()

        # reading session from read/read_start/read_end
        read = row.get("read", "").strip()
        rs, _ = _parse_date(row.get("read_start", ""), dayfirst=False)
        re_, _ = _parse_date(row.get("read_end", ""), dayfirst=False)
        if read in _TRUE or rs or re_:
            if not copy.reading_sessions:
                copy.reading_sessions.append(
                    m.ReadingSession(
                        started=rs, finished=re_,
                        status="read" if read in _TRUE else "reading",
                    )
                )

        self.stats["rows"] += 1
        return copy

    def attach_covers(self):
        """Map <book_uuid>.jpg from the .bcbk backup onto editions, by Copy.legacy_book_uuid."""
        path = os.path.join(self.data_dir, Config.BACKUP_BCBK)
        if not os.path.exists(path):
            return
        with tarfile.open(path) as tf:
            names = {n[:-4] for n in tf.getnames() if n.endswith(".jpg")}
        for copy in self.s.query(m.Copy).filter(m.Copy.legacy_book_uuid.isnot(None)):
            if copy.legacy_book_uuid in names and copy.edition and not copy.edition.cover_path:
                copy.edition.cover_path = f"covers/{copy.legacy_book_uuid}.jpg"
                self.stats["covers"] += 1

    def run(self):
        path = os.path.join(self.data_dir, Config.MASTER_CSV)
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                self.import_row(row)
        self.attach_covers()
        self.s.commit()
        from .search import reindex
        reindex(self.s)
        return self.stats


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False
