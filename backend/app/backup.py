"""
Backups. Three kinds, all UTF-8 / Greek-safe:
  * database_sql()  — full Postgres dump via pg_dump (authoritative restore)
  * library/wishlist CSV — see export.py
  * full_zip()      — portable archive: CSVs + thumbnails + db dump + linking manifest +
                      README, so the data is usable/linkable in any app and movable to any box.

Timestamps follow the yyyy.mm.dd.hh.mm convention.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import tarfile
import tempfile
import zipfile

from sqlalchemy.engine import make_url

from .config import Config
from . import export
from . import models as m


def timestamp() -> str:
    return dt.datetime.now().strftime("%Y.%m.%d.%H.%M")


def database_sql() -> bytes:
    """Run pg_dump against the configured database and return the SQL dump bytes."""
    u = make_url(Config.DATABASE_URL)
    env = dict(os.environ, PGPASSWORD=u.password or "")
    cmd = ["pg_dump", "--clean", "--if-exists",
           "-h", u.host or "localhost", "-p", str(u.port or 5432),
           "-U", u.username or "loa", "-d", u.database or "loa"]
    proc = subprocess.run(cmd, capture_output=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace") or "pg_dump failed")
    return proc.stdout


README = """Library of Alexandria — portable backup
========================================
Contents:
  library.csv    One row per owned copy (UTF-8 with BOM). Column `legacy_book_uuid`
                 links to a thumbnail in covers/ named <legacy_book_uuid>.jpg (when present).
  wishlist.csv   Wanted books (UTF-8 with BOM).
  database.sql   Full PostgreSQL dump. Restore with:  psql -d <db> < database.sql
  covers/        Cover thumbnails, filename = <legacy_book_uuid>.jpg
  README.txt     This file.

This archive is self-describing and app-independent: the CSVs are plain UTF-8 and the
covers link by the legacy_book_uuid column, so the data is usable in any other tool.
To move to another machine: restore database.sql, or re-import library.csv.
"""


def write_full_zip(s) -> str:
    """Build the portable zip on disk; returns its temp path (caller deletes it)."""
    fd, path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("library.csv", export.library_csv(s))
        z.writestr("wishlist.csv", export.wishlist_csv(s))
        try:
            z.writestr("database.sql", database_sql())
        except Exception as e:                       # don't lose the rest if pg_dump fails
            z.writestr("database.sql.ERROR.txt", f"pg_dump failed: {e}")
        z.writestr("README.txt", README)

        # thumbnails from the .bcbk backup, linked by legacy_book_uuid
        bcbk = os.path.join(Config.DATA_DIR, Config.BACKUP_BCBK)
        if os.path.exists(bcbk):
            with tarfile.open(bcbk) as tf:
                names = {n for n in tf.getnames() if n.endswith(".jpg")}
                uuids = [x[0] for x in s.query(m.Copy.legacy_book_uuid)
                         .filter(m.Copy.legacy_book_uuid.isnot(None)).all()]
                for uuid in uuids:
                    fn = f"{uuid}.jpg"
                    if fn in names:
                        member = tf.extractfile(fn)
                        if member:
                            z.writestr(f"covers/{fn}", member.read())
    return path
