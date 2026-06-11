"""Flexible CSV import tests."""
from app.csvimport import parse_csv, commit
from app import models as m


def test_parse_detects_columns():
    data = "Title,Author,ISBN13,Publisher,Year\nDune,Herbert Frank,9780441013593,Ace,1965\n".encode()
    r = parse_csv(data)
    assert r["total"] == 1
    row = r["rows"][0]
    assert row["title"] == "Dune" and row["isbn"] == "9780441013593"
    assert row["year"] == "1965" and row["eligible"] is True


def test_parse_greek_and_arbitrary_columns():
    data = "name,creator,random\nΜατωμένα χώματα,Sotiriou Dido,x\n".encode("utf-8")
    r = parse_csv(data)
    assert r["rows"][0]["title"] == "Ματωμένα χώματα"        # 'name' -> title, Greek intact


def test_commit_to_wishlist_and_library(session):
    assert commit(session, [{"title": "Wanted", "authors": ["A"], "isbn": "", "asin": ""}],
                  "wishlist")["added"] == 1
    assert session.query(m.WishlistItem).count() == 1
    assert commit(session, [{"title": "Owned", "authors": ["B, C"], "isbn": "9780441013593"}],
                  "library")["added"] == 1
    assert session.query(m.Work).filter(m.Work.title == "Owned").count() == 1


def test_commit_into_collection(session):
    col = m.Collection(name="Imp", kind="library")
    session.add(col); session.commit()
    commit(session, [{"title": "InColl", "authors": ["A"]}], "library", collection_id=col.id)
    w = session.query(m.Work).filter(m.Work.title == "InColl").one()
    assert session.query(m.CollectionWork).filter_by(collection_id=col.id, work_id=w.id).count() == 1
