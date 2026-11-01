"""Фидбек-раунд 2026-10-28: стратификация вердиктов по таймлайну, уверенность.
2026-10-29: вердикты параллельно (3 потока), бюджет предвыделяется до пула."""
import time

from videofactcheck import config, pipeline, store, tracing
from videofactcheck import verdict as ve
from videofactcheck.pipeline import _select_for_verdicts


def _c(i, t):
    return {"hash": str(i), "t_start": t}


def test_stratification_covers_whole_timeline():
    """Фидбек-6: у 43-мин видео все вердикты не должны сбиваться в первые минуты."""
    claims = [_c(i, i * 100) for i in range(25)]  # 25 утверждений на 0..2400с
    picked = _select_for_verdicts(claims, 15)
    ts = [c["t_start"] for c in picked]
    assert len(picked) == 15
    assert max(ts) > 2000, "последние минуты видео должны быть покрыты"
    assert min(ts) < 200, "и первые тоже"


def test_stratification_small_list_passthrough():
    claims = [_c(0, 0), _c(1, 10)]
    assert _select_for_verdicts(claims, 15) == claims


def test_confidence_levels():
    """Формула уверенности: согласие проходов + качество источников."""
    votes_hi = [{"trust": 0.9}, {"trust": 0.8}]
    votes_mid = [{"trust": 0.5}]
    votes_weak = [{"trust": 0.1}]
    assert ve._confidence(["правда", "правда"], votes_hi) == "высокая"
    assert ve._confidence(["правда", "правда"], votes_mid) == "средняя"
    assert ve._confidence(["ложно", "ложно"], votes_weak) == "низкая"
    assert ve._confidence(["правда", "ложно"], votes_hi) == "низкая"  # разошлись
    assert ve._confidence(["правда", "правда"], []) == "низкая"  # вердикт без источников сомнителен


# ── этап 2.5: научное правдоподобие прикрепляется к вердикту ────────────────

def test_plausibility_attached_to_verdict(monkeypatch, tmp_path):
    """Слой включён, plausibility.check замокан: refutes прикрепляется к result
    как блок plausibility; verdict остаётся от sonar (косвенное ≠ «ложно»)."""
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
    assert saved["verdict"] == "странно"          # вердикт не заменён косвенным
    assert saved["plausibility"]["relation"] == "refutes"
    assert saved["plausibility"]["source"]["year"] == "2019"


# ── конвейер ClaimReview (фидбек 29.10 «сущности быстрее») ──────────────────

def test_claimreview_pipeline_via_on_batch(monkeypatch, tmp_path):
    """ClaimReview проверяет утверждения по мере батчей (on_batch), до конца
    экстракции; повторный матчинг hit-claims после экстракции не происходит."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "0")  # без сети; слой тестируется отдельно
    monkeypatch.setattr(tracing, "client", lambda: None)
    t = {"title": "T", "video_id": "v", "duration": 60.0, "lang": "ru",
         "sub_kind": "client", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    claims = [_full_claim(0), _full_claim(1)]
    calls = {"match": 0, "sonar": 0}

    def fake_extract(segments, lang="ru", title="", concurrency=4, progress=None, on_batch=None, **kw):
        if on_batch:
            on_batch([claims[0]])  # первый батч приехал до «конца» экстракции
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
    assert saved[claims[0]["claim"]]["why"].startswith("Проверено людьми")  # конвейерный вердикт
    assert saved[claims[1]["claim"]]["verdict"] == "ложно"  # sonar-слой жив
    # claim 0 заматчен дважды (on_batch + слой 1 после) — допустимо, но вердикт один;
    # sonar по нему не гонялся
    assert calls["sonar"] == 1


# ── язык проверки (v0.6.2, ревью P1-5) ──────────────────────────────────────

def test_verdict_lang_reaches_both_layers(monkeypatch, tmp_path):
    """verdict_lang='en' из запроса доходит и до sonar, и до ClaimReview-слоя;
    язык транскрипта (ru) при этом не перебивает настройку."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "0")  # без сети; слой тестируется отдельно
    monkeypatch.setattr(tracing, "client", lambda: None)
    t = {"title": "T", "video_id": "v", "duration": 60.0, "lang": "ru",
         "sub_kind": "client", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    monkeypatch.setattr(pipeline.claims_mod, "extract",
                        lambda *a, **kw: {"claims": [_full_claim(0)], "skipped": []})
    seen = {}

    def fake_match(claim, lang="ru"):
        seen["human"] = lang
        return None  # ClaimReview промахнулся → claim уйдёт в sonar

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
    assert seen["sonar"] == "en"   # настройка дошла до sonar
    assert seen["human"] == "en"   # и до ClaimReview-слоя


# ── параллельные вердикты (2026-10-29) ─────────────────────────────────────

def _full_claim(i: int) -> dict:
    return {"hash": f"h{i}", "quote": f"цитата {i}", "claim": f"утверждение {i}",
            "t_start": float(i * 60), "t_end": float(i * 60 + 5),
            "type": "факт", "category": "история"}


def _mocked_run(monkeypatch, tmp_path, claims: list[dict], *, check_delay: float = 0.0):
    """Полный синхронный прогон _run: клиентский transcript, экстракция и оба
    слоя вердиктов замоканы. Возвращает (замыкание run(install_id), state)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.delenv("VFC_DEV_UNLIMITED", raising=False)
    monkeypatch.setenv("VFC_PLAUSIBILITY", "0")  # без сети; слой тестируется отдельно  # в .env разработки =1
    monkeypatch.setattr(tracing, "client", lambda: None)  # langfuse отключён — без сети
    t = {"title": "Тест", "video_id": "vid", "duration": 600.0, "lang": "ru",
         "sub_kind": "auto", "cues": [{"start": 0.0, "end": 2.0, "text": "текст"}]}
    monkeypatch.setattr(pipeline.claims_mod, "extract",
                        lambda *a, **kw: {"claims": claims, "skipped": []})
    monkeypatch.setattr(pipeline.factcheck_db, "match", lambda claim, lang="ru": None)
    state = {"sonar": [], "phases": []}

    def fake_check(claim, lang="ru", passes=2, title=""):
        state["sonar"].append(claim)  # list.append атомарен — счётчик без lock
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
    """6 вердиктов × 0.2с в 3 потока ≈ 0.4с, а не 1.2с; все сохранены, фаза доходит до 6/6."""
    claims = [_full_claim(i) for i in range(6)]
    run, state = _mocked_run(monkeypatch, tmp_path, claims, check_delay=0.2)
    run_id = run()
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    assert state["elapsed"] < 0.6, f"пул не распараллелил: {state['elapsed']:.2f}с"
    assert len(state["sonar"]) == 6  # порядок вызовов не важен — все дошли
    assert set(state["sonar"]) == {c["claim"] for c in claims}
    saved = {c["hash"]: c for c in st["claims"]}
    assert len(saved) == 6
    assert all(c["verdict"] == "правда" for c in saved.values())  # порядок не важен, все на месте
    assert "verdict 6/6" in state["phases"]  # прогресс дошёл до конца
    assert st["summary"]["checked"] == 6


def test_budget_caps_sonar_at_budget_left(monkeypatch, tmp_path):
    """budget=2 → ровно 2 sonar-вызова, остальные 4 сохранены без вердикта; settle списал 2."""
    run, state = _mocked_run(monkeypatch, tmp_path, [_full_claim(i) for i in range(6)])
    install = "inst-budget"
    store.settle(install, store.FREE_DAILY - 2)  # выжимаем квоту до 2
    assert store.budget(install) == 2
    run_id = run(install)
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    assert len(state["sonar"]) == 2, f"budget=2, а sonar-вызовов {len(state['sonar'])}"
    saved = st["claims"]
    assert len(saved) == 6
    assert sum(1 for c in saved if c["verdict"] is not None) == 2
    assert sum(1 for c in saved if c["verdict"] is None) == 4  # остальные — None
    assert all(c["result"] is None or "claim_meta" in c["result"]
               for c in saved if c["verdict"] is None)  # метаданные экстракции допустимы
    assert store.get_or_create_account(install)["free_left_today"] == 0  # settle(install, 2)


def test_sonar_failure_does_not_kill_run(monkeypatch, tmp_path):
    """Упавший sonar не валит прогон: claim сохранён без вердикта, остальные проверены."""
    claims = [_full_claim(i) for i in range(3)]
    run, state = _mocked_run(monkeypatch, tmp_path, claims)

    def flaky_check(claim, lang="ru", passes=2, title=""):
        if "1" in claim:  # средний из трёх падает
            raise RuntimeError("sonar timeout")
        return {"verdict": "правда", "why": "ок", "votes": [], "relevant": 0,
                "confidence": "средняя", "engine": "sonar", "passes": ["sonar", "sonar"]}

    monkeypatch.setattr(pipeline.verdict_mod, "check", flaky_check)
    run_id = run()
    st = pipeline.get_status(run_id)
    assert st["status"] == "done", st.get("error")
    saved = {c["hash"]: c for c in st["claims"]}
    assert saved["h1"]["verdict"] is None  # упавший — без вердикта
    assert saved["h0"]["verdict"] == "правда" and saved["h2"]["verdict"] == "правда"
    assert st["summary"]["checked"] == 2
    assert "verdict 3/3" in state["phases"]  # K считает и упавшие как завершённые


# ── CJK-утечка научного слоя (наблюдалась вживую: why на китайском вопреки промпту) ──

def _plaus_env(monkeypatch, replies):
    """Мок plausibility: _en_query/_pmc/_openalex статичны, llm.chat идёт по списку."""
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
    """Китайский why переспрашивается: пользователь видит русский, не 摘要."""
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
    assert calls["n"] == 2  # первый ответ отброшен, второй принят


def test_plausibility_cjk_gives_up(monkeypatch):
    """Устойчивая утечка (3 попытки) — слой молчит, китайский блок не показывается."""
    import json as _json
    cjk = _json.dumps({"relation": "supports", "why": "米诺地尔是有效的血管扩张剂。",
                       "quote": "minoxidil is a vasodilator", "article": 0},
                      ensure_ascii=False)
    pl, calls = _plaus_env(monkeypatch, [cjk])
    assert pl.check("Миноксидил расширяет сосуды", "ru") is None
    assert calls["n"] == 3  # лимит попыток


# ── шаг 2 дилеммы: гварды релевантности + fuse (2026-10-30, v0.7.0) ────────────

def _guard_env(monkeypatch, llm_reply, article):
    """Мок plausibility с управляемой статьёй и ответом NLI."""
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
    """Смежная статья (ксеростомия vs синдром отмены) — блок без влияния."""
    pl = _guard_env(monkeypatch, _nli(relevance="adjacent"), _art(year="2024"))
    out = pl.check("X", "ru")
    assert out["relation"] == "refutes" and out["influential"] is False


def test_plaus_relevance_missing_defaults_adjacent(monkeypatch):
    """NLI не выдал relevance — осторожный дефолт: не влияет."""
    import json as _json
    reply = _json.dumps({"relation": "refutes", "why": "Наука против.",
                         "quote": "q", "article": 0}, ensure_ascii=False)
    pl = _guard_env(monkeypatch, reply, _art(year="2024"))
    out = pl.check("X", "ru")
    assert out["relevance"] == "adjacent" and out["influential"] is False


def test_plaus_old_primary_blocked_review_passes(monkeypatch):
    """Старая (2012) статья-первоисточник не влияет; обзор любого года — влияет."""
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
    assert r["verdict"] == "правда"  # исходник не мутируется


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
        assert fuse(r, "ru") is r  # без гвардов — тот же объект без изменений
    # «странно» наука не трогает вовсе
    r2 = {"verdict": "странно", "why": "w",
          "plausibility": {"relation": "refutes", "influential": True, "why": "x"}}
    assert fuse(r2, "ru") is r2
