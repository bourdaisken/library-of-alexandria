"""
Test fixtures.

IMPORTANT: tests run against a DEDICATED `loa_test` database (auto-created), never the
production `loa` DB — so running pytest can never wipe your real catalog. We force this by
rewriting DATABASE_URL *before* the app modules import their engine.
"""
import os

import sqlalchemy as sa

_main = os.environ.get("DATABASE_URL", "postgresql+psycopg2://loa:loa@localhost:5432/loa")
_base, _db = _main.rsplit("/", 1)
_test_db = "loa_test"
if _db != _test_db:
    # create loa_test if missing (connect to the maintenance 'postgres' db)
    _admin = sa.create_engine(f"{_base}/postgres", isolation_level="AUTOCOMMIT")
    with _admin.connect() as c:
        if not c.execute(sa.text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": _test_db}).scalar():
            c.execute(sa.text(f"CREATE DATABASE {_test_db}"))
    _admin.dispose()
    os.environ["DATABASE_URL"] = f"{_base}/{_test_db}"

import pytest                       # noqa: E402
from sqlalchemy import text         # noqa: E402

from app.db import Session, engine, init_db   # noqa: E402  (imports AFTER env rewrite)
from app.models import Base                    # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    # rebuild loa_test from current models each run, so schema changes always apply
    Base.metadata.drop_all(engine)
    init_db()
    yield


@pytest.fixture
def session():
    """Clean DB per test (in loa_test): truncate every table, then hand back the session."""
    s = Session()
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    s.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    s.commit()
    yield s
    Session.remove()
