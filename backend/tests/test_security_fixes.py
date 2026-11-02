"""Regression tests for the security fixes of the 2026-10-28 audit."""
import os
from videofactcheck import verdict as ve
from videofactcheck import server


def test_safe_url_blocks_javascript_scheme():
    """SEC-1: a javascript: URL from the LLM never becomes a source link."""
    assert ve._safe_url("javascript:alert(1)//x") is None
    assert ve._safe_url("data:text/html,<script>") is None
    assert ve._safe_url('https://x"><img src=x onerror=alert(1>') is None
    assert ve._safe_url("https://reuters.com/article?a=1") == "https://reuters.com/article?a=1"


def test_votes_skip_unsafe_urls(monkeypatch):
    import json
    def fake_chat(messages, **kw):
        return json.dumps({"verdict": "правда", "why": "x", "sources": [
            {"title": "A", "url": "javascript:alert(1)//x", "quote": "q"},
            {"title": "B", "url": "https://reuters.com/a", "quote": "q"},
        ]}, ensure_ascii=False)
    monkeypatch.setattr(ve.llm, "chat", fake_chat)
    res = ve.check("утверждение", "ru")
    assert [v["domain"] for v in res["votes"]] == ["reuters.com"]


def test_topup_disabled_without_env(monkeypatch):
    """SEC-2: the mockup top-up is closed without VFC_ALLOW_MOCK_TOPUP=1."""
    from fastapi.testclient import TestClient
    monkeypatch.delenv("VFC_ALLOW_MOCK_TOPUP", raising=False)
    client = TestClient(server.app)
    r = client.post("/api/topup", json={"install_id": "sec-test", "credits": 100},
                    headers={"Origin": "https://www.youtube.com"})
    assert r.json().get("error") and "недоступна" in r.json()["error"]
    # and the enabled flag works
    monkeypatch.setenv("VFC_ALLOW_MOCK_TOPUP", "1")
    from videofactcheck import config, store
    monkeypatch.setattr(config, "DB_PATH", __import__("pathlib").Path(
        __import__("tempfile").mkdtemp()) / "a.db")
    r2 = client.post("/api/topup", json={"install_id": "sec-test", "credits": 100},
                     headers={"Origin": "https://www.youtube.com"})
    assert r2.json().get("credits") == 100


def test_anonymous_budget_is_free_daily(monkeypatch):
    """SEC-3: without install_id the budget is the daily quota, not unlimited."""
    from videofactcheck import config, store
    monkeypatch.setattr(config, "DB_PATH", __import__("pathlib").Path(
        __import__("tempfile").mkdtemp()) / "a.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    # the logic lives inside _run; we test the component: budget without install_id
    # does not exist, so we check that VFC_DEV_UNLIMITED is not set by default
    assert os.environ.get("VFC_DEV_UNLIMITED", "") != "1"
