"""Collections (library + wishlist) tests."""
from app.catalog import add_book, add_wishlist
from app import query as q
from app import models as m


def test_library_collection_filter(session):
    w, e, c = add_book(session, {"title": "A", "authors": ["X, Y"], "copy": {}})
    add_book(session, {"title": "B", "authors": ["Z, W"], "copy": {}})
    col = m.Collection(name="Faves", kind="library")
    session.add(col); session.commit()
    session.add(m.CollectionWork(collection_id=col.id, work_id=w.id)); session.commit()
    res = q.build_works_query(session, collection_id=col.id).all()
    assert [x.title for x in res] == ["A"]


def test_wishlist_collection(session):
    col = m.Collection(name="To buy in Greece", kind="wishlist")
    session.add(col); session.commit()
    it = add_wishlist(session, {"title": "Wanted", "collection_id": col.id})
    assert it.collection_id == col.id
