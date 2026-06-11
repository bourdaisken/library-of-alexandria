"""BiblioNet client parsing + cover enrichment (offline; network is monkeypatched)."""
from app import biblionet
from app.catalog import add_book
from app import enrichment
from app import models as m

# A minimal BiblioNet result page: one card with the hidden print_r() dump.
SAMPLE = """<html><body>
<pre>Array
(
    [title_id] => 308561
    [title] => Αναφορά στον Γκρέκο
    [summary] => Μια αυτοβιογραφική αφήγηση.
    [publish_date] => 1262304000
    [image_url] => /assets/images/books/book_308561/cover.webp
    [isbn] => 978-618-6000-11-9
    [isbn2] =>
    [isbn3] =>
    [pages] => 94
    [lang] => Ελληνικά
    [publisher_id] => 77
    [contributors] => Array
        (
            [0] => Array
                (
                    [name] => Νίκος Καζαντζάκης
                    [role] => Συγγραφέας
                )

        )

)</pre>
</body></html>"""


def test_parse_and_normalise(monkeypatch):
    monkeypatch.setattr(biblionet, "_fetch", lambda q, timeout=18.0: SAMPLE)
    meta = biblionet.lookup_isbn("978-618-6000-11-9")
    assert meta is not None
    assert meta["title"] == "Αναφορά στον Γκρέκο"          # Greek intact
    assert meta["authors"] == ["Νίκος Καζαντζάκης"]
    assert meta["published_date"] == "2010"                 # unix ts -> year, not "1262"
    assert meta["pages"] == "94"
    assert meta["cover_url"] == "https://biblionet.gr/assets/images/books/book_308561/cover.webp"
    assert meta["source"] == "biblionet"


def test_isbn_mismatch_returns_none(monkeypatch):
    monkeypatch.setattr(biblionet, "_fetch", lambda q, timeout=18.0: SAMPLE)
    assert biblionet.lookup_isbn("9780000000000") is None


def test_enrichment_proposes_and_applies_cover(session, monkeypatch):
    add_book(session, {"title": "X", "authors": ["A, B"], "isbn": "9786186000119", "copy": {}})
    ed = session.query(m.Edition).one()
    assert not ed.cover_path

    # Stub the source lookup to return a cover URL + description.
    monkeypatch.setattr(enrichment, "lookup",
                        lambda isbn, session=None: {"cover_url": "http://x/c.webp",
                                                    "description": "desc", "source": "biblionet"})
    # Stub the actual download so the test stays offline.
    def fake_store(s, edition, url, source="enrichment", timeout=20.0):
        c = m.CoverImage(edition_id=edition.id, data=b"\x89PNG", content_type="image/webp", source=source)
        s.add(c); edition.cover_path = f"db:{edition.id}"; return True
    monkeypatch.setattr("app.covers.store_cover_from_url", fake_store)

    run = enrichment.dry_run(session)
    fields = {p.field for p in run.proposals}
    assert "cover" in fields and "description" in fields

    enrichment.commit(session, run.id, mode="all")
    ed = session.query(m.Edition).one()
    assert ed.cover_path == f"db:{ed.id}"
    assert session.get(m.CoverImage, ed.id) is not None


def test_apply_candidate_fills_only_gaps(session, monkeypatch):
    add_book(session, {"title": "Ελληνικό Βιβλίο", "authors": ["Α, Β"], "copy": {}})
    ed = session.query(m.Edition).one()
    assert not ed.isbn13 and not ed.cover_path and not ed.description

    def fake_store(s, edition, url, source="match", timeout=20.0):
        s.add(m.CoverImage(edition_id=edition.id, data=b"x", content_type="image/webp", source=source))
        edition.cover_path = f"db:{edition.id}"
        return True
    monkeypatch.setattr("app.covers.store_cover_from_url", fake_store)

    cand = {"title": "Ελληνικό Βιβλίο", "description": "περίληψη", "pages": "120",
            "published_date": "2010", "isbn": "9786186000119",
            "cover_url": "http://x/c.webp", "source": "biblionet"}
    applied = enrichment.apply_candidate(session, ed.id, cand)
    assert {"description", "pages", "published_year", "isbn", "cover"}.issubset(set(applied))
    ed = session.query(m.Edition).one()
    assert ed.description == "περίληψη" and ed.pages == 120 and ed.published_year == 2010
    assert ed.isbn13 == "9786186000119" and ed.cover_path == f"db:{ed.id}"


def test_apply_candidate_title_and_author_forms(session, monkeypatch):
    add_book(session, {"title": "Anafora ston Greko", "authors": ["Kazantzakis, Nikos"],
                       "isbn": "9786186000119", "copy": {}})
    ed = session.query(m.Edition).one()
    monkeypatch.setattr("app.covers.store_cover_from_url", lambda *a, **k: False)
    cand = {"title": "Αναφορά στον Γκρέκο", "authors": ["Νίκος Καζαντζάκης"], "source": "biblionet"}
    applied = enrichment.apply_candidate(session, ed.id, cand, update_title=True, add_author_forms=True)
    assert "title" in applied and "author name" in applied
    w = session.query(m.Work).one()
    assert w.title == "Αναφορά στον Γκρέκο"                 # transliteration replaced
    author = w.contributors[0].author
    forms = {nf.name_form for nf in author.name_forms}
    assert "Νίκος Καζαντζάκης" in forms                     # Greek form ADDED
    assert author.canonical_name == "Kazantzakis, Nikos"   # Latin form KEPT


def test_apply_candidate_default_leaves_title_and_authors(session, monkeypatch):
    add_book(session, {"title": "Keep Me", "authors": ["A, B"], "isbn": "9786186000119", "copy": {}})
    ed = session.query(m.Edition).one()
    monkeypatch.setattr("app.covers.store_cover_from_url", lambda *a, **k: False)
    enrichment.apply_candidate(session, ed.id, {"title": "Other", "authors": ["Γ Δ"]})
    w = session.query(m.Work).one()
    assert w.title == "Keep Me"                              # untouched without the flags
    assert {nf.name_form for nf in w.contributors[0].author.name_forms} == {"A, B"}


def test_apply_candidate_keeps_existing_values(session, monkeypatch):
    add_book(session, {"title": "T", "authors": ["A, B"], "isbn": "9780000000019",
                       "description": "mine", "copy": {}})
    ed = session.query(m.Edition).one()
    monkeypatch.setattr("app.covers.store_cover_from_url", lambda *a, **k: False)
    applied = enrichment.apply_candidate(session, ed.id, {"description": "theirs", "isbn": "9786186000119"})
    assert "description" not in applied and "isbn" not in applied   # both already set
    assert session.query(m.Edition).one().description == "mine"
