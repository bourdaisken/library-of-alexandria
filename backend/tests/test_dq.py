"""Data-quality studio: distinct values, clustering, replace/merge."""
from app.catalog import add_book
from app.dq import field_values, cluster_values, replace_value
from app import models as m


def test_replace_plain_column(session):
    add_book(session, {"title": "A", "authors": ["X, Y"], "format": "softcover", "copy": {}})
    add_book(session, {"title": "B", "authors": ["Z, W"], "format": "Paperback", "copy": {}})
    add_book(session, {"title": "C", "authors": ["P, Q"], "format": "paperback", "copy": {}})
    assert {v["value"] for v in field_values(session, "edition.format")} == {"softcover", "Paperback", "paperback"}
    res = replace_value(session, "edition.format", ["softcover", "paperback"], "Paperback")
    assert res["ok"]
    vals = {v["value"]: v["count"] for v in field_values(session, "edition.format")}
    assert vals == {"Paperback": 3}


def test_cluster_groups_case_and_space(session):
    for i, fmt in enumerate(["Paperback", "paperback", "PAPERBACK "]):
        add_book(session, {"title": f"T{i}", "authors": ["A, B"], "format": fmt, "copy": {}})
    clusters = cluster_values(session, "edition.format")
    assert any(len({v["value"] for v in c["values"]}) >= 2 for c in clusters)


def test_merge_authors_reassigns(session):
    add_book(session, {"title": "A", "authors": ["Smith, John"], "copy": {}})
    add_book(session, {"title": "B", "authors": ["smith, john"], "copy": {}})
    assert session.query(m.Author).filter(m.Author.canonical_name.in_(["Smith, John", "smith, john"])).count() == 2
    replace_value(session, "author.canonical_name", ["smith, john"], "Smith, John")
    assert session.query(m.Author).filter(m.Author.canonical_name == "smith, john").count() == 0
    a = session.query(m.Author).filter(m.Author.canonical_name == "Smith, John").one()
    assert session.query(m.WorkContributor).filter_by(author_id=a.id).count() == 2


def test_merge_tags(session):
    add_book(session, {"title": "A", "authors": ["X, Y"], "tags": ["Scifi"], "copy": {}})
    add_book(session, {"title": "B", "authors": ["Z, W"], "tags": ["scifi"], "copy": {}})
    replace_value(session, "tag.name", ["scifi"], "Scifi")
    assert session.query(m.Tag).filter(m.Tag.name == "scifi").count() == 0
    assert session.query(m.Tag).filter(m.Tag.name == "Scifi").count() == 1
