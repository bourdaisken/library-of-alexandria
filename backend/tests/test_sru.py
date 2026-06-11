"""SRU MARCXML/Dublin-Core parsing for user-added catalogue sources (network mocked)."""
from app import sru
from app import titlesearch
from app.settings import set_setting

MARC = """<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
<records><record><recordData>
<record xmlns="http://www.loc.gov/MARC21/slim">
  <controlfield tag="008">050101s2005    nyu           eng</controlfield>
  <datafield tag="020"><subfield code="a">9780441013593 (pbk.)</subfield></datafield>
  <datafield tag="100"><subfield code="a">Herbert, Frank.</subfield></datafield>
  <datafield tag="245"><subfield code="a">Dune /</subfield><subfield code="b">Frank Herbert.</subfield></datafield>
  <datafield tag="264"><subfield code="b">Ace Books,</subfield><subfield code="c">2005.</subfield></datafield>
</record>
</recordData></record></records></searchRetrieveResponse>"""


class _Resp:
    def __init__(self, data): self.data = data
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_sru_parses_marcxml(monkeypatch):
    monkeypatch.setattr(sru.urllib.request, "urlopen", lambda req, timeout=15.0: _Resp(MARC.encode()))
    res = sru.search("http://example/sru?query={q}", "dune")
    assert len(res) == 1
    c = res[0]
    assert "Dune" in c["title"]
    assert c["authors"] == ["Herbert, Frank."]
    assert c["isbn"] == "9780441013593"
    assert c["published_date"] == "2005"
    assert c["publisher"].startswith("Ace Books")
    assert c["cover_url"].endswith("9780441013593-M.jpg?default=false")


def test_sru_bad_response_returns_empty(monkeypatch):
    monkeypatch.setattr(sru.urllib.request, "urlopen", lambda req, timeout=15.0: _Resp(b"<html>nope</html>"))
    assert sru.search("http://example/sru?query={q}", "x") == []


def test_custom_source_appears_in_titlesearch(session, monkeypatch):
    set_setting("custom_sources", [{"key": "loc", "name": "Library of Congress",
                                    "url": "http://example/sru?query={q}"}])
    keys = {s["key"] for s in titlesearch.available()}
    assert "custom:loc" in keys
    monkeypatch.setattr(sru.urllib.request, "urlopen", lambda req, timeout=15.0: _Resp(MARC.encode()))
    res = titlesearch.search(["custom:loc"], "dune")
    assert res and res[0]["source"] == "Library of Congress"
