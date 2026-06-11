"""Book edit + delete cascade tests."""
from app.catalog import add_book, update_book
from app import models as m


def test_update_book_flat(session):
    w, e, c = add_book(session, {"title": "Old", "authors": ["A, B"],
                                 "isbn": "9780441013593", "copy": {"location": "S1"}})
    update_book(session, w.id, {
        "title": "New Title", "authors": ["Γ, Δ"], "publisher": "PubX",
        "tags": ["sci-fi"], "edition_id": e.id, "copy_id": c.id,
        "copy": {"location": "Shelf 9", "notes": "hi", "signed": True},
    })
    session.expire_all()
    w2 = session.get(m.Work, w.id)
    assert w2.title == "New Title"
    assert w2.contributors[0].author.canonical_name == "Γ, Δ"     # greek + replaced author
    assert w2.editions[0].publisher == "PubX"
    cp = w2.editions[0].copies[0]
    assert cp.location == "Shelf 9" and cp.signed is True and cp.notes == "hi"


def test_delete_work_cascades(session):
    w, e, c = add_book(session, {"title": "X", "authors": ["A, B"], "copy": {}})
    session.delete(w)
    session.commit()
    assert session.query(m.Work).count() == 0
    assert session.query(m.Edition).count() == 0
    assert session.query(m.Copy).count() == 0
