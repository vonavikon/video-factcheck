"""Feedback round 2026-10-28: timeline stratification of verdicts, confidence.
2026-10-29: verdicts in parallel (3 threads), the budget is pre-allocated before the pool."""
import time

from videofactcheck import config, pipeline, store, tracing
from videofactcheck import verdict as ve
from videofactcheck.pipeline import _select_for_verdicts


def _c(i, t):
    return {"hash": str(i), "t_start": t}


def test_stratification_covers_whole_timeline():
    """Feedback item 6: for a 43-min video, all verdicts must not pile up in the first minutes."""
    claims = [_c(i, i * 100) for i in range(25)]  # 25 claims over 0..2400s
    picked = _select_for_verdicts(claims, 15)
    ts = [c["t_start"] for c in picked]
    assert len(picked) == 15
    assert max(ts) > 2000, "последние минуты видео должны быть покрыты"
    assert min(ts) < 200, "и первые тоже"


def test_stratification_small_list_passthrough():
    claims = [_c(0, 0), _c(1, 10)]
    assert _select_for_verdicts(claims, 15) == claims


def test_confidence_levels():
    """The confidence formula: pass agreement + source quality."""
    votes_hi = [{"trust": 0.9}, {"trust": 0.8}]
    votes_mid = [{"trust": 0.5}]
    votes_weak = [{"trust": 0.1}]
    assert ve._confidence(["правда", "правда"], votes_hi) == "высокая"
    assert ve._confidence(["правда", "правда"], votes_mid) == "средняя"
    assert ve._confidence(["ложно", "ложно"], votes_weak) == "низкая"
    assert ve._confidence(["правда", "ложно"], votes_hi) == "низкая"  # passes disagreed
    assert ve._confidence(["правда", "правда"], []) == "низкая"  # a verdict without sources is doubtful


# ── stage 2.5: scientific plausibility attaches to the verdict ───────────────

def test_plausibility_attached_to_verdict(monkeypatch, tmp_path):
    """The layer is enabled, plausibility.check is mocked: refutes attaches to result
    as the plausibility block; the verdict stays sonar's (indirect ≠ "ложно")."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "1")
    monkeypatch.setattr(tracing, "client", lambda: None)
    t = {"title": "T", "video_id": "v", "duration": 60.0, "lang": "ru",
         "sub_kind": "client", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    claims = [_full_claim(0)]
    monkeypatch.setattr(pipeline.claims_mod, "extract",
                        lambda *a, **kw: {"claims": claims, "skipped": []})
    monkeypatch.setattr(pipeline.factcheck_db, "match", lambda claim, lang="ru": None)

    def fake_check(claim, lang="ru", passes=2, title=""):
        return {"verdict": "странно", "why": "нет источников", "votes": [], "relevant": 0,
                "confidence": "низкая", "engine": "sonar", "passes": ["sonar", "sonar"]}

    monkeypatch.setattr(pipeline.verdict_mod, "check", fake_check)
    plaus = {"relation": "refutes", "why": "наука депривации сна противоречит",
             "quote": "sleep deprivation degrades performance",
             "source": {"title": "Sleep and Cognition", "url": "https://europepmc.org/x", "year": "2019"}}
    monkeypatch.setattr(pipeline.plaus_mod, "check", lambda claim, lang="ru": plaus)
    run_id = store.new_run("", "https://youtube.com/watch?v=v")
    pipeline._run(run_id, "https://youtube.com/watch?v=v", t, "")
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    saved = st["claims"][0]["result"]
    assert saved["verdict"] == "странно"          # the verdict is not replaced by indirect evidence
    assert saved["plausibility"]["relation"] == "refutes"
    assert saved["plausibility"]["source"]["year"] == "2019"


# ── ClaimReview pipeline (29.10 feedback: "entities faster") ─────────────────

def test_claimreview_pipeline_via_on_batch(monkeypatch, tmp_path):
    """ClaimReview checks claims as batches arrive (on_batch), before extraction
    finishes; hit-claims are not matched again after extraction."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "0")  # no network; the layer is tested separately
    monkeypatch.setattr(tracing, "client", lambda: None)
    t = {"title": "T", "video_id": "v", "duration": 60.0, "lang": "ru",
         "sub_kind": "client", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    claims = [_full_claim(0), _full_claim(1)]
    calls = {"match": 0, "sonar": 0}

    def fake_extract(segments, lang="ru", title="", concurrency=4, progress=None, on_batch=None, **kw):
        if on_batch:
            on_batch([claims[0]])  # the first batch arrived before extraction "finished"
        return {"claims": claims, "skipped": []}

    human = {"verdict": "правда", "why": "Проверено людьми (X): «true»", "votes": [],
             "relevant": 1, "confidence": "высокая", "engine": "claimreview", "passes": ["human"]}

    def fake_match(claim, lang="ru"):
        calls["match"] += 1
        return human if "0" in claim else None

    def fake_check(claim, lang="ru", passes=2, title=""):
        calls["sonar"] += 1
        return {"verdict": "ложно", "why": "sonar", "votes": [], "relevant": 0,
                "confidence": "средняя", "engine": "sonar", "passes": ["sonar", "sonar"]}

    monkeypatch.setattr(pipeline.claims_mod, "extract", fake_extract)
    monkeypatch.setattr(pipeline.factcheck_db, "match", fake_match)
    monkeypatch.setattr(pipeline.verdict_mod, "check", fake_check)
    run_id = store.new_run("", "https://youtube.com/watch?v=v")
    pipeline._run(run_id, "https://youtube.com/watch?v=v", t, "")
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    saved = {c["claim"]: c for c in st["claims"]}
    assert saved[claims[0]["claim"]]["why"].startswith("Проверено людьми")  # pipelined verdict
    assert saved[claims[1]["claim"]]["verdict"] == "ложно"  # the sonar layer is alive
    # claim 0 was matched twice (on_batch + layer 1 afterwards), acceptable, but the verdict is one;
    # sonar was not run on it
    assert calls["sonar"] == 1


# ── check language (v0.6.2, review P1-5) ────────────────────────────────────

def test_verdict_lang_reaches_both_layers(monkeypatch, tmp_path):
    """verdict_lang='en' from the request reaches both sonar and the ClaimReview layer;
    the transcript language (ru) does not override the setting."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "0")  # no network; the layer is tested separately
    monkeypatch.setattr(tracing, "client", lambda: None)
    t = {"title": "T", "video_id": "v", "duration": 60.0, "lang": "ru",
         "sub_kind": "client", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    monkeypatch.setattr(pipeline.claims_mod, "extract",
                        lambda *a, **kw: {"claims": [_full_claim(0)], "skipped": []})
    seen = {}

    def fake_match(claim, lang="ru"):
        seen["human"] = lang
        return None  # ClaimReview missed → the claim goes to sonar

    def fake_check(claim, lang="ru", passes=2, title=""):
        seen["sonar"] = lang
        return {"verdict": "правда", "why": "x", "votes": [], "relevant": 0,
                "confidence": "средняя", "engine": "sonar", "passes": ["sonar", "sonar"]}

    monkeypatch.setattr(pipeline.factcheck_db, "match", fake_match)
    monkeypatch.setattr(pipeline.verdict_mod, "check", fake_check)
    run_id = store.new_run("", "https://youtube.com/watch?v=v")
    pipeline._run(run_id, "https://youtube.com/watch?v=v", t, "", "en")
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    assert seen["sonar"] == "en"   # the setting reached sonar
    assert seen["human"] == "en"   # and the ClaimReview layer


# ── parallel verdicts (2026-10-29) ──────────────────────────────────────────

def _full_claim(i: int) -> dict:
    return {"hash": f"h{i}", "quote": f"цитата {i}", "claim": f"утверждение {i}",
            "t_start": float(i * 60), "t_end": float(i * 60 + 5),
            "type": "факт", "category": "история"}


def _mocked_run(monkeypatch, tmp_path, claims: list[dict], *, check_delay: float = 0.0):
    """A full synchronous _run: client transcript, extraction and both verdict
    layers mocked. Returns (a run(install_id) closure, state)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "0")  # no network; the layer is tested separately  # =1 in the dev .env
    monkeypatch.setattr(tracing, "client", lambda: None)  # langfuse disabled, no network
    t = {"title": "Тест", "video_id": "vid", "duration": 600.0, "lang": "ru",
         "sub_kind": "auto", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    monkeypatch.setattr(pipeline.claims_mod, "extract",
                        lambda *a, **kw: {"claims": claims, "skipped": []})
    monkeypatch.setattr(pipeline.factcheck_db, "match", lambda claim, lang="ru": None)
    state = {"sonar": [], "phases": []}

    def fake_check(claim, lang="ru", passes=2, title=""):
        state["sonar"].append(claim)  # list.append is atomic, a counter without a lock
        if check_delay:
            time.sleep(check_delay)
        return {"verdict": "правда", "why": "мок-вердикт", "votes": [], "relevant": 0,
                "confidence": "средняя", "engine": "sonar", "passes": ["sonar", "sonar"]}

    monkeypatch.setattr(pipeline.verdict_mod, "check", fake_check)
    real_update = store.update_run

    def spy_update(run_id, **kw):
        if kw.get("phase"):
            state["phases"].append(kw["phase"])
        return real_update(run_id, **kw)

    monkeypatch.setattr(store, "update_run", spy_update)

    def run(install_id: str = "") -> str:
        run_id = store.new_run("", "https://youtube.com/watch?v=x")
        t0 = time.monotonic()
        pipeline._run(run_id, "https://youtube.com/watch?v=x", t, install_id)
        state["elapsed"] = time.monotonic() - t0
        return run_id

    return run, state


def test_verdicts_parallel_3_workers(monkeypatch, tmp_path):
    """6 verdicts × 0.2s over 3 threads ≈ 0.4s, not 1.2s; all saved, the phase reaches 6/6."""
    claims = [_full_claim(i) for i in range(6)]
    run, state = _mocked_run(monkeypatch, tmp_path, claims, check_delay=0.2)
    run_id = run()
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    assert state["elapsed"] < 0.6, f"пул не распараллелил: {state['elapsed']:.2f}с"
    assert len(state["sonar"]) == 6  # call order does not matter, all arrived
    assert set(state["sonar"]) == {c["claim"] for c in claims}
    saved = {c["hash"]: c for c in st["claims"]}
    assert len(saved) == 6
    assert all(c["verdict"] == "правда" for c in saved.values())  # order does not matter, all present
    assert "verdict 6/6" in state["phases"]  # progress reached the end
    assert st["summary"]["checked"] == 6


def test_budget_caps_sonar_at_budget_left(monkeypatch, tmp_path):
    """budget=2 → exactly 2 sonar calls, the other 4 saved without a verdict; settle charged 2."""
    run, state = _mocked_run(monkeypatch, tmp_path, [_full_claim(i) for i in range(6)])
    install = "inst-budget"
    store.settle(install, store.FREE_DAILY - 2)  # squeeze the quota down to 2
    assert store.budget(install) == 2
    run_id = run(install)
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    assert len(state["sonar"]) == 2, f"budget=2, а sonar-вызовов {len(state['sonar'])}"
    saved = st["claims"]
    assert len(saved) == 6
    assert sum(1 for c in saved if c["verdict"] is not None) == 2
    assert sum(1 for c in saved if c["verdict"] is None) == 4  # the rest are None
    assert all(c["result"] is None or "claim_meta" in c["result"]
               for c in saved if c["verdict"] is None)  # extraction metadata is allowed
    assert store.get_or_create_account(install)["free_left_today"] == 0  # settle(install, 2)


def test_sonar_failure_does_not_kill_run(monkeypatch, tmp_path):
    """A failed sonar does not kill the run: the claim is saved without a verdict, the rest are checked."""
    claims = [_full_claim(i) for i in range(3)]
    run, state = _mocked_run(monkeypatch, tmp_path, claims)

    def flaky_check(claim, lang="ru", passes=2, title=""):
        if "1" in claim:  # the middle one of three fails
            raise RuntimeError("sonar timeout")
        return {"verdict": "правда", "why": "ок", "votes": [], "relevant": 0,
                "confidence": "средняя", "engine": "sonar", "passes": ["sonar", "sonar"]}

    monkeypatch.setattr(pipeline.verdict_mod, "check", flaky_check)
    run_id = run()
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    saved = {c["hash"]: c for c in st["claims"]}
    assert saved["h1"]["verdict"] is None  # the failed one, no verdict
    assert saved["h0"]["verdict"] == "правда" and saved["h2"]["verdict"] == "правда"
    assert st["summary"]["checked"] == 2
    assert "verdict 3/3" in state["phases"]  # K counts failed ones as finished too


# ── science layer CJK leakage (observed live: why in Chinese against the prompt) ──

def _plaus_env(monkeypatch, replies):
    """A plausibility mock: _en_query/_pmc/_openalex are static, llm.chat walks the list."""
    import videofactcheck.plausibility as pl
    calls = {"n": 0}

    def fake_chat(messages, **kw):
        out = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return out

    monkeypatch.setattr(pl.llm, "chat", fake_chat)
    monkeypatch.setattr(pl, "_en_query", lambda c, l: "minoxidil hypertension")
    monkeypatch.setattr(pl, "_pmc",
                        lambda q: [{"title": "T", "abstract": "A" * 200, "year": "2025", "url": "u"}])
    monkeypatch.setattr(pl, "_openalex", lambda q: [])
    return pl, calls


def test_plausibility_cjk_retry(monkeypatch):
    """A Chinese why is retried: the user sees Russian, not 摘要."""
    import json as _json
    cjk = _json.dumps({"relation": "supports", "why": "摘要1指出米诺地尔是抗高血压药物。",
                       "quote": "minoxidil was developed as an antihypertensive", "article": 0},
                      ensure_ascii=False)
    good = _json.dumps({"relation": "supports", "why": "Исследования подтверждают.",
                        "quote": "minoxidil was developed as an antihypertensive", "article": 0},
                       ensure_ascii=False)
    pl, calls = _plaus_env(monkeypatch, [cjk, good])
    out = pl.check("Миноксидил снижает давление", "ru")
    assert out and out["why"] == "Исследования подтверждают."
    assert calls["n"] == 2  # the first answer is discarded, the second accepted


def test_plausibility_cjk_gives_up(monkeypatch):
    """Persistent leakage (3 attempts); the layer stays silent, the Chinese block is not shown."""
    import json as _json
    cjk = _json.dumps({"relation": "supports", "why": "米诺地尔是有效的血管扩张剂。",
                       "quote": "minoxidil is a vasodilator", "article": 0},
                      ensure_ascii=False)
    pl, calls = _plaus_env(monkeypatch, [cjk])
    assert pl.check("Миноксидил расширяет сосуды", "ru") is None
    assert calls["n"] == 3  # attempt limit


# ── dilemma step 2: relevance guards + fuse (2026-10-30, v0.7.0) ────────────

def _guard_env(monkeypatch, llm_reply, article):
    """A plausibility mock with a controllable article and NLI reply."""
    import json as _json
    import videofactcheck.plausibility as pl
    monkeypatch.setattr(pl.llm, "chat", lambda messages, **kw: llm_reply)
    monkeypatch.setattr(pl, "_en_query", lambda c, l: "q")
    monkeypatch.setattr(pl, "_pmc", lambda q: [article])
    monkeypatch.setattr(pl, "_openalex", lambda q: [])
    return pl


def _art(year="2020", kind="primary"):
    return {"title": "T", "abstract": "A" * 200, "year": year, "url": "u", "kind": kind}


def _nli(relation="refutes", relevance="directly_on_topic"):
    import json as _json
    return _json.dumps({"relation": relation, "relevance": relevance,
                        "why": "Наука против.", "quote": "quote text", "article": 0},
                       ensure_ascii=False)


def test_plaus_relevance_direct_modern_influential(monkeypatch):
    pl = _guard_env(monkeypatch, _nli(), _art(year="2020"))
    out = pl.check("X", "ru")
    assert out["influential"] is True and out["relevance"] == "directly_on_topic"


def test_plaus_relevance_adjacent_never_influential(monkeypatch):
    """An adjacent article (xerostomia vs withdrawal syndrome): a block without influence."""
    pl = _guard_env(monkeypatch, _nli(relevance="adjacent"), _art(year="2024"))
    out = pl.check("X", "ru")
    assert out["relation"] == "refutes" and out["influential"] is False


def test_plaus_relevance_missing_defaults_adjacent(monkeypatch):
    """The NLI gave no relevance; cautious default: not influential."""
    import json as _json
    reply = _json.dumps({"relation": "refutes", "why": "Наука против.",
                         "quote": "q", "article": 0}, ensure_ascii=False)
    pl = _guard_env(monkeypatch, reply, _art(year="2024"))
    out = pl.check("X", "ru")
    assert out["relevance"] == "adjacent" and out["influential"] is False


def test_plaus_old_primary_blocked_review_passes(monkeypatch):
    """An old (2012) primary article does not influence; a review of any year does."""
    pl = _guard_env(monkeypatch, _nli(), _art(year="2012", kind="primary"))
    assert pl.check("X", "ru")["influential"] is False
    pl2 = _guard_env(monkeypatch, _nli(), _art(year="2012", kind="review"))
    assert pl2.check("X", "ru")["influential"] is True


def test_fuse_downgrades_true_to_strange():
    from videofactcheck.verdict import fuse
    r = {"verdict": "правда", "why": "Интернет подтверждает.",
         "confidence": "высокая", "plausibility": {
             "relation": "refutes", "influential": True, "why": "Наука против."}}
    out = fuse(r, "ru")
    assert out["verdict"] == "странно" and out["verdict_raw"] == "правда"
    assert out["confidence"] == "низкая" and out["science_flip"] == "refutes"
    assert "Интернет подтверждает." in out["why"] and "Наука против." in out["why"]
    assert r["verdict"] == "правда"  # the original is not mutated


def test_fuse_false_with_supports_and_guards():
    from videofactcheck.verdict import fuse
    r = {"verdict": "ложно", "why": "Web says false.",
         "confidence": "средняя", "plausibility": {
             "relation": "supports", "influential": True, "why": "Science agrees."}}
    out = fuse(r, "en")
    assert out["verdict"] == "странно" and out["science_flip"] == "supports"
    assert "Scientific evidence supports this:" in out["why"]


def test_fuse_noop_without_guards():
    from videofactcheck.verdict import fuse
    for rel, v in (("refutes", "правда"), ("supports", "ложно")):
        r = {"verdict": v, "why": "w", "confidence": "высокая",
             "plausibility": {"relation": rel, "influential": False, "why": "x"}}
        assert fuse(r, "ru") is r  # without guards, the same object unchanged
    # science never touches "странно" at all
    r2 = {"verdict": "странно", "why": "w",
          "plausibility": {"relation": "refutes", "influential": True, "why": "x"}}
    assert fuse(r2, "ru") is r2
