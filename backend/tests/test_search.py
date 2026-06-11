"""Full-text ranking + pg_trgm fuzzy/typo tolerance."""
from app.catalog import add_book
from app import query as q
from app.search import reindex


def _titles(session, **kw):
    return [w.title for w in q.build_works_query(session, **kw).all()]


def test_ranking_weights_title_over_description(session):
    add_book(session, {"title": "The Great Gatsby", "authors": ["Fitzgerald, F. Scott"], "copy": {}})
    add_book(session, {"title": "Gardening Basics", "authors": ["Green, Pat"],
                       "description": "all about gatsby gardens", "copy": {}})
    reindex(session)
    res = _titles(session, q="gatsby")
    assert res and res[0] == "The Great Gatsby"        # title (A) outranks description (D)


def test_fuzzy_typo_match(session):
    add_book(session, {"title": "The Great Gatsby", "authors": ["Fitzgerald, F. Scott"], "copy": {}})
    reindex(session)
    assert "The Great Gatsby" in _titles(session, q="gatsbi")   # typo still found (trigram)
    assert "The Great Gatsby" in _titles(session, q="Fitzgerald")  # author via full text


def test_greek_fulltext(session):
    add_book(session, {"title": "Η Ιστορία του Καραγκιόζη", "authors": ["Παπαδόπουλος, Γιάννης"], "copy": {}})
    reindex(session)
    assert _titles(session, q="Καραγκιόζη")            # Greek tokenised + matched
