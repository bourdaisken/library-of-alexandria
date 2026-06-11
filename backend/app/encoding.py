"""
Encoding-integrity utilities — the cross-cutting CORE requirement.

Greek and every other script must remain byte-faithful end to end. Every piece of text
entering the system passes through `normalize_text()`:
  * NFC Unicode normalization (consistent search/sort, non-destructive)
  * safe mojibake repair (only when it strictly reduces damage; clean text is untouched)

`is_damaged()` / `damage_score()` are also used by tests to assert no corruption survives.
"""
import re
import unicodedata

try:
    from ftfy import fix_encoding
except ImportError:  # pragma: no cover - ftfy is a hard dependency, this is a safety net
    fix_encoding = None

REPLACEMENT = "�"

# A suspicious lead char (Ã Â Î Ï Å) followed by a non-alphanumeric, or the â€ smart-punct
# signature. Spares legitimate letters (São, Île, Ångström -> lead followed by a letter).
_MOJIBAKE = re.compile(r"â€|[ÃÂÎÏÅ][^\sA-Za-z0-9]")


def damage_score(s: str) -> int:
    if not s:
        return 0
    return s.count(REPLACEMENT) * 5 + len(_MOJIBAKE.findall(s))


def is_damaged(s: str) -> bool:
    if not s:
        return False
    return (REPLACEMENT in s) or (_MOJIBAKE.search(s) is not None)


def repair_mojibake(s: str) -> str:
    """Reverse double-encoding without ever increasing damage. No-op on clean text."""
    if not s or not is_damaged(s):
        return s
    best, best_score = s, damage_score(s)
    candidates = []
    if fix_encoding is not None:
        try:
            candidates.append(fix_encoding(s))
        except Exception:
            pass
    for enc in ("cp1252", "latin-1"):
        try:
            candidates.append(s.encode(enc).decode("utf-8"))
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    for c in candidates:
        sc = damage_score(c)
        if sc < best_score:
            best, best_score = c, sc
    return best


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s) if s else s


def normalize_text(s):
    """The single entry point for all inbound text. None/empty pass through unchanged."""
    if s is None:
        return None
    if not isinstance(s, str):
        return s
    return nfc(repair_mojibake(s))
