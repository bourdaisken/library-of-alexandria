"""
Full-text search index (PostgreSQL tsvector) + pg_trgm fuzzy matching.

reindex() (re)builds the per-work `work_search` rows in one SQL statement, weighting:
  A = title, B = authors, C = series/publisher/tags, D = description/notes.
Uses the 'simple' text-search config (no stemming) so every language — incl. Greek — works;
pg_trgm on the plain `text` adds typo/fuzzy tolerance across scripts.

Called after import / e-book folder scan / add / edit; also lazily on first search.
"""
from __future__ import annotations

from sqlalchemy import text

_setup_done = False

_REINDEX_SQL = """
INSERT INTO work_search (work_id, text, doc)
SELECT w.id,
  btrim(concat_ws(' ', w.title, au.agg_auth, s.name, ed.agg_pub, tg.agg_tag, ed.agg_desc, cp.agg_notes)) AS text,
  setweight(to_tsvector('simple', coalesce(w.title,'')), 'A') ||
  setweight(to_tsvector('simple', coalesce(au.agg_auth,'')), 'B') ||
  setweight(to_tsvector('simple', concat_ws(' ', s.name, ed.agg_pub, tg.agg_tag)), 'C') ||
  setweight(to_tsvector('simple', concat_ws(' ', ed.agg_desc, cp.agg_notes)), 'D') AS doc
FROM works w
LEFT JOIN series s ON s.id = w.series_id
LEFT JOIN LATERAL (SELECT concat_ws(' ',
                          string_agg(DISTINCT a.canonical_name, ' '),
                          string_agg(DISTINCT anf.name_form, ' ')) AS agg_auth
                   FROM work_contributors wc JOIN authors a ON a.id = wc.author_id
                   LEFT JOIN author_name_forms anf ON anf.author_id = a.id
                   WHERE wc.work_id = w.id) au ON true
LEFT JOIN LATERAL (SELECT string_agg(DISTINCT e.publisher, ' ') AS agg_pub,
                          string_agg(DISTINCT e.description, ' ') AS agg_desc
                   FROM editions e WHERE e.work_id = w.id) ed ON true
LEFT JOIN LATERAL (SELECT string_agg(DISTINCT c.notes, ' ') AS agg_notes
                   FROM editions e JOIN copies c ON c.edition_id = e.id
                   WHERE e.work_id = w.id) cp ON true
LEFT JOIN LATERAL (SELECT string_agg(DISTINCT t.name, ' ') AS agg_tag
                   FROM work_tags wt JOIN tags t ON t.id = wt.tag_id
                   WHERE wt.work_id = w.id) tg ON true
{where}
ON CONFLICT (work_id) DO UPDATE SET text = EXCLUDED.text, doc = EXCLUDED.doc;
"""


def ensure_search_setup(session):
    """Create the pg_trgm extension + GIN indexes once (idempotent)."""
    global _setup_done
    if _setup_done:
        return
    session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    session.execute(text("CREATE INDEX IF NOT EXISTS ix_work_search_doc ON work_search USING gin(doc)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS ix_work_search_text_trgm "
                         "ON work_search USING gin(text gin_trgm_ops)"))
    session.commit()
    _setup_done = True


def reindex(session, work_id=None):
    """Rebuild the search index for all works, or just one (after add/edit)."""
    ensure_search_setup(session)
    where = "WHERE w.id = :wid" if work_id else ""
    session.execute(text(_REINDEX_SQL.format(where=where)), {"wid": work_id} if work_id else {})
    session.commit()
