"""
3-tier WEMI data model: Work -> Edition -> Copy, plus contributors, series, tags,
reading sessions, loans, wishlist, users, and the enrichment-proposal tables.

The 3-tier WEMI data model (Work -> Edition -> Copy).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- people
class Author(Base, TimestampMixin):
    __tablename__ = "authors"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    canonical_name: Mapped[str] = mapped_column(Text)          # display/canonical form
    sort_name: Mapped[str] = mapped_column(Text, index=True)   # "Family, Given"
    birth_year: Mapped[int | None] = mapped_column(Integer)
    death_year: Mapped[int | None] = mapped_column(Integer)
    complete_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    name_forms: Mapped[list["AuthorNameForm"]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )


class AuthorNameForm(Base):
    """Every name variant from the source, stored VERBATIM (no semantic merge in v1)."""
    __tablename__ = "author_name_forms"
    __table_args__ = (UniqueConstraint("author_id", "name_form"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    author_id: Mapped[str] = mapped_column(ForeignKey("authors.id", ondelete="CASCADE"))
    name_form: Mapped[str] = mapped_column(Text)
    author: Mapped[Author] = relationship(back_populates="name_forms")


class Series(Base, TimestampMixin):
    __tablename__ = "series"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)


# --------------------------------------------------------------------------- WORK
class Work(Base, TimestampMixin):
    __tablename__ = "works"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(Text, index=True)
    sort_title: Mapped[str] = mapped_column(Text, index=True)
    original_language: Mapped[str | None] = mapped_column(String(20))
    series_id: Mapped[str | None] = mapped_column(ForeignKey("series.id"))
    series_position: Mapped[str | None] = mapped_column(String(20))

    series: Mapped[Series | None] = relationship()
    editions: Mapped[list["Edition"]] = relationship(back_populates="work", cascade="all, delete-orphan")
    contributors: Mapped[list["WorkContributor"]] = relationship(cascade="all, delete-orphan")
    tags: Mapped[list["WorkTag"]] = relationship(cascade="all, delete-orphan")
    identifiers: Mapped[list["WorkIdentifier"]] = relationship(cascade="all, delete-orphan")


class WorkContributor(Base):
    __tablename__ = "work_contributors"
    __table_args__ = (UniqueConstraint("work_id", "author_id", "role"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"))
    author_id: Mapped[str] = mapped_column(ForeignKey("authors.id"))
    role: Mapped[str] = mapped_column(String(40), default="author")
    author: Mapped[Author] = relationship()


class WorkTag(Base):
    __tablename__ = "work_tags"
    __table_args__ = (UniqueConstraint("work_id", "tag_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"))
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"))
    tag: Mapped[Tag] = relationship()


class WorkIdentifier(Base):
    __tablename__ = "work_identifiers"
    __table_args__ = (UniqueConstraint("work_id", "scheme"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"))
    scheme: Mapped[str] = mapped_column(String(40))   # olid_work, goodreads_work, ...
    value: Mapped[str] = mapped_column(Text)


# --------------------------------------------------------------------------- EDITION
class Edition(Base, TimestampMixin):
    __tablename__ = "editions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"))
    isbn13: Mapped[str | None] = mapped_column(String(13), index=True)
    isbn10: Mapped[str | None] = mapped_column(String(10), index=True)
    publisher: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[dt.date | None] = mapped_column(Date)
    published_year: Mapped[int | None] = mapped_column(Integer)   # for year-only / partial dates
    pages: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str | None] = mapped_column(String(20))
    list_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    list_price_currency: Mapped[str | None] = mapped_column(String(3))   # per-record, default GBP
    cover_path: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    work: Mapped[Work] = relationship(back_populates="editions")
    copies: Mapped[list["Copy"]] = relationship(back_populates="edition", cascade="all, delete-orphan")
    contributors: Mapped[list["EditionContributor"]] = relationship(cascade="all, delete-orphan")
    identifiers: Mapped[list["EditionIdentifier"]] = relationship(cascade="all, delete-orphan")


class EditionContributor(Base):
    __tablename__ = "edition_contributors"
    __table_args__ = (UniqueConstraint("edition_id", "author_id", "role"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"))
    author_id: Mapped[str] = mapped_column(ForeignKey("authors.id"))
    role: Mapped[str] = mapped_column(String(40))   # translator, narrator, ...
    author: Mapped[Author] = relationship()


class EditionIdentifier(Base):
    __tablename__ = "edition_identifiers"
    __table_args__ = (UniqueConstraint("edition_id", "scheme"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"))
    scheme: Mapped[str] = mapped_column(String(40))   # isbn13, isbn10, asin, goodreads, olid, google, isfdb, ...
    value: Mapped[str] = mapped_column(Text)


# --------------------------------------------------------------------------- COPY
class Copy(Base, TimestampMixin):
    __tablename__ = "copies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="physical")        # physical|ebook|audio
    copy_type: Mapped[str] = mapped_column(String(20), default="reading")    # reading|collectible|photocopy|lending|archive
    condition: Mapped[str | None] = mapped_column(String(20))                # new|used
    condition_grade: Mapped[str | None] = mapped_column(String(20))          # Fine|VG|Good|Fair|Poor
    location: Mapped[str | None] = mapped_column(Text)                       # physical shelf OR e-file path
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    acquired_date: Mapped[dt.date | None] = mapped_column(Date)
    acquisition_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    acquisition_currency: Mapped[str | None] = mapped_column(String(3))
    current_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    current_value_currency: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(Text)                          # provenance + personal comments
    file_ref: Mapped[str | None] = mapped_column(Text)                       # absolute path of the e-book file (folder scan)
    legacy_book_uuid: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)

    edition: Mapped[Edition] = relationship(back_populates="copies")
    reading_sessions: Mapped[list["ReadingSession"]] = relationship(cascade="all, delete-orphan")
    loans: Mapped[list["Loan"]] = relationship(cascade="all, delete-orphan")


class ReadingSession(Base):
    __tablename__ = "reading_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    copy_id: Mapped[str] = mapped_column(ForeignKey("copies.id", ondelete="CASCADE"))
    started: Mapped[dt.date | None] = mapped_column(Date)
    finished: Mapped[dt.date | None] = mapped_column(Date)
    progress_pct: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="unread")   # unread|reading|read


class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    copy_id: Mapped[str] = mapped_column(ForeignKey("copies.id", ondelete="CASCADE"))
    borrower: Mapped[str | None] = mapped_column(Text)
    lent_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    returned_date: Mapped[dt.date | None] = mapped_column(Date)


class Collection(Base, TimestampMixin):
    """A user-defined grouping. kind='library' groups Works (via CollectionWork);
    kind='wishlist' groups WishlistItems (via WishlistItem.collection_id)."""
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("name", "kind"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))   # library | wishlist


class CollectionWork(Base):
    __tablename__ = "collection_works"
    __table_args__ = (UniqueConstraint("collection_id", "work_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"))
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"))


class WishlistItem(Base, TimestampMixin):
    __tablename__ = "wishlist_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    collection_id: Mapped[str | None] = mapped_column(ForeignKey("collections.id"))
    work_id: Mapped[str | None] = mapped_column(ForeignKey("works.id"))
    edition_id: Mapped[str | None] = mapped_column(ForeignKey("editions.id"))
    title: Mapped[str | None] = mapped_column(Text)
    target_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    priority: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class WorkSearch(Base):
    """Per-work full-text index. `doc` = weighted tsvector (title/author/…); `text` feeds
    pg_trgm fuzzy matching. Rebuilt by app.search.reindex (extension + GIN indexes added there)."""
    __tablename__ = "work_search"
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), primary_key=True)
    text: Mapped[str | None] = mapped_column(Text)
    doc: Mapped[str | None] = mapped_column(TSVECTOR)


class LibraryMap(Base, TimestampMixin):
    """A 3D map for one physical area, matched to locations by prefix.
    e.g. area='UK' (location 'UK 33') -> name 'UK Office', asset_path to the widget HTML.
    Add more (Greece, Living Room…) as you build them."""
    __tablename__ = "library_maps"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    area: Mapped[str] = mapped_column(String(80), unique=True, index=True)   # location prefix
    name: Mapped[str] = mapped_column(Text)
    asset_path: Mapped[str] = mapped_column(Text)                            # e.g. /static/…html


class EnrichmentSource(Base):
    """A metadata source for enrichment/lookup. `key` maps to a built-in fetcher."""
    __tablename__ = "enrichment_sources"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(40), unique=True)   # openlibrary | google | ...
    name: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)


class Setting(Base, TimestampMixin):
    """Generic key/value app settings (JSON-encoded value). e.g. ebooks_dir, bookren_config."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)   # JSON-encoded


class CoverImage(Base, TimestampMixin):
    """A cover fetched from the web (e.g. BiblioNet) stored IN the DB so it's offline
    and travels with pg_dump backups. Edition.cover_path = 'db:<edition_id>' points here."""
    __tablename__ = "cover_images"
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    source: Mapped[str | None] = mapped_column(String(40))


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user")   # admin|user|readonly


# --------------------------------------------------------------- enrichment proposals
class EnrichmentRun(Base, TimestampMixin):
    __tablename__ = "enrichment_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    mode: Mapped[str] = mapped_column(String(20))      # dry_run
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|committed|discarded
    source: Mapped[str | None] = mapped_column(String(40))             # openlibrary|google|...
    note: Mapped[str | None] = mapped_column(Text)

    proposals: Mapped[list["EnrichmentProposal"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EnrichmentProposal(Base):
    """A single field-level proposed change, reviewable and selectively committable."""
    __tablename__ = "enrichment_proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("enrichment_runs.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(20))   # edition|work
    entity_id: Mapped[str] = mapped_column(String(32))
    field: Mapped[str] = mapped_column(String(40))
    current_value: Mapped[str | None] = mapped_column(Text)
    proposed_value: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(10))   # add (field empty) | change (differs)
    source: Mapped[str | None] = mapped_column(String(40))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    committed: Mapped[bool] = mapped_column(Boolean, default=False)
    committed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[EnrichmentRun] = relationship(back_populates="proposals")
