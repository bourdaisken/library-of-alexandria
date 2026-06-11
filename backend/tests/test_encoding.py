"""Encoding-integrity unit tests — the CORE requirement. No DB needed."""
from app.encoding import normalize_text, is_damaged, repair_mojibake, nfc


def test_clean_text_is_untouched():
    for s in ["Πανούσης, Τζίμης", "de Balzac, Honoré", "Miciński, Tadeusz", "Müeller, Michael"]:
        assert normalize_text(s) == nfc(s)
        assert not is_damaged(normalize_text(s))


def test_mojibake_is_reversed():
    assert repair_mojibake("DalÃ­") == "Dalí"
    assert repair_mojibake("MÃ¼eller") == "Müeller"
    assert repair_mojibake("Î±Î²Î³") == "αβγ"
    assert repair_mojibake("JaffÃ©") == "Jaffé"


def test_repair_never_increases_damage():
    # A clean Greek string must never be "fixed" into something worse.
    clean = "Ξηρός, Σάββας"
    assert repair_mojibake(clean) == clean


def test_round_trip_bytes_are_utf8_faithful():
    for s in ["Ξηρός", "Honoré", "Müeller", "Miciński", "café"]:
        norm = normalize_text(s)
        assert norm.encode("utf-8").decode("utf-8") == norm


def test_none_and_nonstr_pass_through():
    assert normalize_text(None) is None
    assert normalize_text(123) == 123
