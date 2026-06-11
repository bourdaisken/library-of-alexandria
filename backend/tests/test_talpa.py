"""TALPA 'describe a book' client — parsing + config guards (network mocked)."""
from app import talpa
from app.config import Config


class _FakeResp:
    def __init__(self, data): self._d = data
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_not_configured(monkeypatch):
    monkeypatch.setattr(Config, "LIBRARYTHING_TALPA_TOKEN", "")
    res = talpa.describe("anything")
    assert res["ok"] is False and not res["results"]


def test_parse_results(monkeypatch):
    monkeypatch.setattr(Config, "LIBRARYTHING_TALPA_TOKEN", "tok")
    payload = (b'{"request":{"developer":{"remaining":49}},'
               b'"response":{"resultlist":['
               b'{"title":"Moby-Dick","work_id":42,"isbns":["123","9780142437247"]},'
               b'{"title":"No ISBN","work_id":7,"isbns":[]}]}}')
    monkeypatch.setattr(talpa.urllib.request, "urlopen", lambda req, timeout=25.0: _FakeResp(payload))
    res = talpa.describe("a whale")
    assert res["ok"] and res["remaining"] == 49
    assert res["results"][0]["title"] == "Moby-Dick"
    assert res["results"][0]["isbn"] == "9780142437247"     # prefers the 13-digit ISBN
    assert res["results"][1]["isbn"] is None


def test_api_error_surfaced(monkeypatch):
    monkeypatch.setattr(Config, "LIBRARYTHING_TALPA_TOKEN", "tok")
    monkeypatch.setattr(talpa.urllib.request, "urlopen",
                        lambda req, timeout=25.0: _FakeResp(b'{"error":{"code":2,"wording":"Token does not exist or is deleted."}}'))
    res = talpa.describe("x")
    assert res["ok"] is False and "Token" in res["error"]
