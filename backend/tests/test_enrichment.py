"""Enrichment tests: dry-run produces a diff (no writes); commit modes behave correctly."""
import app.enrichment as enrichment
from app import models as m


def _make_edition(session, **kw):
    w = m.Work(title="Dune", sort_title="Dune")
    session.add(w)
    session.flush()
    ed = m.Edition(work_id=w.id, isbn13="9780441013593", **kw)
    session.add(ed)
    session.commit()
    return ed


def _fake_lookup(result):
    return lambda isbn: result


def test_dry_run_writes_nothing_but_proposes(session, monkeypatch):
    ed = _make_edition(session, description=None, publisher="Ace", pages=None)
    monkeypatch.setattr(enrichment, "lookup",
                        _fake_lookup({"description": "Επικό μυθιστόρημα", "pages": 412,
                                      "publisher": "Ace", "source": "openlibrary"}))
    run = enrichment.dry_run(session)
    session.expire_all()
    # record itself is unchanged by a dry run
    assert session.get(m.Edition, ed.id).description is None
    d = enrichment.diff(session, run.id)
    fields = {p["field"]: p for p in d["proposals"]}
    assert fields["description"]["change_type"] == "add"          # was empty
    assert fields["description"]["proposed"] == "Επικό μυθιστόρημα"
    assert fields["pages"]["change_type"] == "add"
    assert "publisher" not in fields                              # identical -> no proposal


def test_commit_all(session, monkeypatch):
    ed = _make_edition(session, description=None, pages=None)
    monkeypatch.setattr(enrichment, "lookup",
                        _fake_lookup({"description": "x", "pages": 412, "source": "g"}))
    run = enrichment.dry_run(session)
    res = enrichment.commit(session, run.id, mode="all")
    assert res["applied"] == 2
    session.expire_all()
    assert session.get(m.Edition, ed.id).pages == 412


def test_commit_selected_only(session, monkeypatch):
    ed = _make_edition(session, description=None, pages=None)
    monkeypatch.setattr(enrichment, "lookup",
                        _fake_lookup({"description": "x", "pages": 412, "source": "g"}))
    run = enrichment.dry_run(session)
    d = enrichment.diff(session, run.id)
    pages_pid = [p["id"] for p in d["proposals"] if p["field"] == "pages"]
    enrichment.select(session, run.id, pages_pid)
    enrichment.commit(session, run.id, mode="selected")
    session.expire_all()
    reloaded = session.get(m.Edition, ed.id)
    assert reloaded.pages == 412            # selected -> applied
    assert reloaded.description is None     # not selected -> untouched


def test_commit_none_does_nothing(session, monkeypatch):
    ed = _make_edition(session, description=None, pages=None)
    monkeypatch.setattr(enrichment, "lookup",
                        _fake_lookup({"description": "x", "pages": 412, "source": "g"}))
    run = enrichment.dry_run(session)
    res = enrichment.commit(session, run.id, mode="none")
    assert res["applied"] == 0
    assert res["status"] == "discarded"
    session.expire_all()
    assert session.get(m.Edition, ed.id).pages is None
