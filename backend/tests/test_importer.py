"""Importer tests: explode -> dedup, idempotency, and encoding survival through the DB."""
from app.importer import Importer
from app import models as m


def _row(**kw):
    base = {
        "_id": "1", "book_uuid": "uuid-1", "author_details": "Herbert, Frank",
        "title": "Dune", "isbn": "ISBN: 9780441013593", "publisher": "Ace",
        "date_published": "01/06/1965", "pages": "412", "format": "Paperback",
        "language": "English", "list_price": "9.99", "series_details": "Dune (1)",
        "genre": "Science Fiction / Classics", "bookshelf": "UK 33,", "read": "1",
        "read_start": "", "read_end": "01/01/2020", "signed": "0", "notes": "",
        "date_added": "26/03/2013", "description": "", "goodreads_book_id": "234225",
    }
    base.update(kw)
    return base


def test_explode_to_three_tiers(session):
    imp = Importer(session=session)
    imp.import_row(_row())
    session.commit()
    assert session.query(m.Work).count() == 1
    assert session.query(m.Edition).count() == 1
    assert session.query(m.Copy).count() == 1
    ed = session.query(m.Edition).one()
    assert ed.isbn13 == "9780441013593"
    cp = session.query(m.Copy).one()
    assert cp.location == "UK 33"            # bookshelf -> physical location, comma trimmed
    assert cp.reading_sessions[0].status == "read"


def test_same_edition_two_copies(session):
    imp = Importer(session=session)
    imp.import_row(_row(book_uuid="uuid-1"))
    imp.import_row(_row(book_uuid="uuid-2"))   # same ISBN, different physical copy
    session.commit()
    assert session.query(m.Edition).count() == 1
    assert session.query(m.Copy).count() == 2


def test_idempotent_on_legacy_uuid(session):
    imp = Importer(session=session)
    imp.import_row(_row(book_uuid="uuid-1", notes="first"))
    imp.import_row(_row(book_uuid="uuid-1", notes="updated"))  # re-import same book
    session.commit()
    assert session.query(m.Copy).count() == 1
    assert session.query(m.Copy).one().notes == "updated"


def test_isbn_less_book_supported(session):
    imp = Importer(session=session)
    imp.import_row(_row(book_uuid="u-noisbn", isbn="", title="Παλιό Βιβλίο"))
    session.commit()
    ed = session.query(m.Edition).filter(m.Edition.work.has(title="Παλιό Βιβλίο")).one()
    assert ed.isbn13 is None


def test_greek_survives_through_db(session):
    imp = Importer(session=session)
    imp.import_row(_row(book_uuid="u-gr", author_details="Ξηρός, Σάββας",
                        title="Ιστορία", isbn="", bookshelf="Greece 2"))
    session.commit()
    session.expire_all()                       # force a real read back from Postgres
    work = session.query(m.Work).filter(m.Work.title == "Ιστορία").one()
    assert work.contributors[0].author.canonical_name == "Ξηρός, Σάββας"
    assert work.title.encode("utf-8").decode("utf-8") == "Ιστορία"


def test_mojibake_repaired_on_import(session):
    imp = Importer(session=session)
    imp.import_row(_row(book_uuid="u-moji", author_details="DalÃ­, Salvador", isbn=""))
    session.commit()
    a = session.query(m.Author).filter(m.Author.sort_name == "Dalí, Salvador").one()
    assert a.canonical_name == "Dalí, Salvador"
