"""Mojibake repair pass — fixes classic double-encoding, never touches Greek/clean text,
and only auto-applies fully-clean results (no lossy replacement chars)."""
from app.mojibake import fix, _acceptable, scan, apply
from app.catalog import add_book
from app import models as m


def test_fix_repairs_classic_mojibake():
    assert fix("JosÃ©") == "José"
    assert fix("SÃ£o Paulo") == "São Paulo"


def test_fix_leaves_greek_and_clean_untouched():
    for t in ["Το Όνομα του Ρόδου", "Καζαντζάκης, Νίκος", "Contrôle (Psychologie)", "Frank Herbert"]:
        assert fix(t) == t


def test_acceptable_rejects_lossy_replacement_char():
    bad = fix("Alzheimer?ï¿½s")   # 'ï¿½' (mojibake of the replacement char)
    assert "�" in bad                       # the apostrophe is already lost
    assert _acceptable(bad) is False             # so we won't write it


def test_scan_and_apply_fix_only_clean(session):
    # Insert RAW mojibake directly (add_book would normalize it away — that guard is good).
    session.add(m.Work(title="SÃ£o Paulo Tales", sort_title="SÃ£o Paulo Tales"))
    session.commit()
    found = scan(session)
    assert any(lbl == "work.title" and new == "São Paulo Tales" for lbl, _, _, new in found["plain"])
    apply(session)
    assert session.query(m.Work).filter(m.Work.title == "São Paulo Tales").count() == 1
    assert session.query(m.Work).filter(m.Work.title == "SÃ£o Paulo Tales").count() == 0
