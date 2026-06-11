"""Model-driven filter/sort/search engine tests."""
from app.catalog import add_book
from app import query as q


def test_fields_are_introspected(session):
    keys = {f["key"] for f in q.fields()}
    assert {"work.title", "edition.publisher", "copy.location", "author.canonical_name"} <= keys
    assert "contains" in q.OPS["text"] and "gt" in q.OPS["int"]


def test_filter_sort_search(session):
    add_book(session, {"title": "Alpha", "authors": ["Zed, A"], "publisher": "PubA",
                       "year": "2001", "copy": {"location": "Shelf 1", "copy_type": "collectible"}})
    add_book(session, {"title": "Beta", "authors": ["Abe, B"], "publisher": "PubB",
                       "year": "1999", "copy": {"location": "Shelf 2"}})

    def titles(**kw):
        return [w.title for w in q.build_works_query(session, **kw).all()]

    assert titles(filters=[{"field": "copy.location", "op": "contains", "value": "Shelf 1"}]) == ["Alpha"]
    assert titles(filters=[{"field": "copy.copy_type", "op": "equals", "value": "collectible"}]) == ["Alpha"]
    assert titles(sort="edition.published_year", direction="asc") == ["Beta", "Alpha"]
    assert titles(sort="edition.published_year", direction="desc") == ["Alpha", "Beta"]
    assert titles(q="Abe", search_field="author.canonical_name") == ["Beta"]   # field-scoped
    assert "Alpha" in titles(q="PubA")                                          # keyword hits publisher
    # invalid field/sort are ignored, not fatal
    assert set(titles(sort="bogus.x", filters=[{"field": "nope.x", "op": "equals", "value": "y"}])) == {"Alpha", "Beta"}
