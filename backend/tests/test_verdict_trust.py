"""Сценарии этапов 4–5: голосование вердиктов, правило цитаты, доверие доменов."""
from videofactcheck import verdict as ve
from videofactcheck import trust


def test_passes_disagree_gives_strange(monkeypatch):
    """CR-VD-01: два прохода разошлись → «странно», а не последний ответ."""
    verdicts = iter(["правда", "ложно"])
    def fake_chat(messages, **kw):
        class T:
            def __init__(self, v):
                import json
                self._v = json.dumps(
                    {"verdict": v, "why": "x", "sources": []}, ensure_ascii=False)
            def strip(self):
                return self._v
        return T(next(verdicts))
    monkeypatch.setattr(ve.llm, "chat", fake_chat)
    res = ve.check("утверждение", "ru", title="t")
    assert res["verdict"] == "странно" and "разошлись" in res["why"]


def test_vote_without_quote_not_counted(monkeypatch):
    """В18: supports без цитаты не засчитывается как источник."""
    import json
    def fake_chat(messages, **kw):
        src = {"title": "T", "url": "https://reuters.com/a", "quote": ""}
        return json.dumps({"verdict": "правда", "why": "x",
                           "sources": [src]}, ensure_ascii=False)
    monkeypatch.setattr(ve.llm, "chat", fake_chat)
    res = ve.check("утверждение", "ru")
    assert res["votes"] == []  # без цитаты — не голос


def test_no_sources_is_strange(monkeypatch):
    import json
    def fake_chat(messages, **kw):
        return json.dumps({"verdict": "странно", "why": "нет данных", "sources": []},
                          ensure_ascii=False)
    monkeypatch.setattr(ve.llm, "chat", fake_chat)
    res = ve.check("утверждение", "ru")
    assert res["verdict"] == "странно" and res["relevant"] == 0


def test_broken_json_pass_is_strange(monkeypatch):
    def fake_chat(messages, **kw):
        return "совсем не json {{{"
    monkeypatch.setattr(ve.llm, "chat", fake_chat)
    res = ve.check("утверждение", "ru")
    assert res["verdict"] == "странно"


def test_invalid_verdict_name_becomes_strange(monkeypatch):
    import json
    def fake_chat(messages, **kw):
        return json.dumps({"verdict": "СООМНЕНИТЕЛЬНО", "why": "", "sources": []},
                          ensure_ascii=False)
    monkeypatch.setattr(ve.llm, "chat", fake_chat)
    res = ve.check("утверждение", "ru")
    assert res["verdict"] == "странно"


def test_trust_domains():
    assert trust.domain_trust("reuters.com") == 1.0
    assert trust.domain_trust("www.reuters.com") == 1.0
    assert trust.domain_trust("uk.reuters.com") == 1.0       # субдомен наследует
    assert trust.domain_trust("reuters.com.evil.ru") == 0.5  # маскировка под домен
    assert trust.domain_trust("unknown-site.xyz") == 0.5
    assert trust.domain_trust("naturalnews.com") == 0.1
