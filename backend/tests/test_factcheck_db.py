"""Stage 2 (ClaimReview): matching, the similarity threshold, rating mapping, fault tolerance."""
import json

from videofactcheck import factcheck_db as fc


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
    def json(self):
        return self._p


def test_no_key_skips_layer(monkeypatch):
    monkeypatch.delenv("VFC_FACTCHECK_KEY", raising=False)
    called = []
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: called.append(1))
    assert fc.match("любое утверждение") is None
    assert called == []


def test_match_with_human_verdict(monkeypatch):
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    payload = {"claims": [{
        "text": "Climate change is a hoax invented by China",
        "claimReview": [{"textualRating": "False", "publisher": {"name": " PolitiFact "},
                          "url": "https://www.politifact.com/article/1", "title": "Fact check"}],
    }]}
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(200, payload))
    res = fc.match("Climate change is a hoax invented by China")
    assert res["verdict"] == "ложно"
    assert res["engine"] == "claimreview"
    assert res["confidence"] == "высокая"
    assert "PolitiFact" in res["why"]
    assert res["votes"][0]["domain"] == "politifact.com"


def test_low_similarity_rejected(monkeypatch):
    """Similar words are present, but the claim is about something else; the layer must not lie with a false hit."""
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    payload = {"claims": [{
        "text": "China invented the paper and gunpowder centuries ago",
        "claimReview": [{"textualRating": "True", "publisher": {"name": "X"},
                          "url": "https://x.com/1", "title": ""}],
    }]}
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(200, payload))
    assert fc.match("Climate change is a hoax invented by China") is None


def test_ru_rating_mapping():
    assert fc._map_rating("Ложь")[0] == "ложно"
    assert fc._map_rating("Правда")[0] == "правда"
    assert fc._map_rating("Вводит в заблуждение")[0] == "странно"
    assert fc._map_rating("Сложно сказать")[0] == "странно"  # unfamiliar scale, cautious


def test_api_error_returns_none(monkeypatch):
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(403, {"error": {}}))
    assert fc.match("x") is None
    def boom(*a, **k):
        raise fc.httpx.ConnectError("net")
    monkeypatch.setattr(fc.httpx, "get", boom)
    assert fc.match("x") is None
