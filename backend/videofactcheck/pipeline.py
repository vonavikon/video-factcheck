"""Оркестратор пайплайна: транскрипт → утверждения → (ClaimReview) → поиск → вердикты.

Этап 2 (ClaimReview) включён ключом VFC_FACTCHECK_KEY (Google Cloud; без ключа
слой пропускается). Расширение получает статус/вердикты через server.py.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import claims as claims_mod
from . import factcheck_db, store, verdict as verdict_mod
from . import plausibility as plaus_mod
from . import transcript as tr
from . import tracing
from .config import MAX_VERDICTS_PER_RUN


def start_run(url: str, transcript: dict | None = None, install_id: str = "",
              verdict_lang: str | None = None) -> dict:
    """Запуск пайплайна в фоне. transcript — клиентский (расширение прочитало
    субтитры со страницы, IP пользователя); None → сервер тянет сам (yt-dlp).
    verdict_lang — язык обоснований вердиктов (настройка расширения «язык
    проверки»); None → язык транскрипта, как раньше."""
    run_id = store.new_run("", url, install_id=install_id)
    threading.Thread(target=_run, args=(run_id, url, transcript, install_id, verdict_lang), daemon=True).start()
    return {"run_id": run_id}


def _run(run_id: str, url: str, transcript: dict | None = None, install_id: str = "",
         verdict_lang: str | None = None) -> None:
    import os as _os
    with tracing.root(run_id, {"url": url}):
        try:
            store.update_run(run_id, phase="transcript")
            with tracing.span("transcript", {"source": "client" if transcript else "yt-dlp"}):
                t = transcript or tr.fetch(url)  # клиентские сабы приоритетнее: без 429
            store.update_run(run_id, title=t["title"], summary={
                "title": t["title"], "duration": t["duration"],
                "video_id": t["video_id"],
            })
            store.save_transcript(t)

            # Конвейер: ClaimReview —
            # бесплатный и мгновенный — проверяет утверждения по мере готовности
            # батчей экстракции, не после неё. Первые карточки «Проверено людьми»
            # приезжают с первыми батчами. sonar остаётся после экстракции:
            # его слоты распределяются стратификацией по таймлайну (фидбек 43-мин).
            hit_hashes: set[str] = set()
            checked = 0  # выданные вердикты (факт-чекерами или sonar) — уходит в summary;
            # объявлен до on_batch: конвейер инкрементит его во время экстракции

            def on_batch(batch_claims) -> None:
                nonlocal checked
                vlang = verdict_lang or t["lang"]
                for c in batch_claims:
                    if c["hash"] in hit_hashes:
                        continue  # батчи до дедупа — один и тот же claim может прийти дважды
                    human = factcheck_db.match(c["claim"], lang=vlang)
                    if human:
                        store.save_claim(run_id, c, human)
                        hit_hashes.add(c["hash"])
                        checked += 1

            with tracing.span("claims"):
                store.update_run(run_id, phase="claims")
                segments = tr.to_segments(t["cues"])
                extracted = claims_mod.extract(
                    segments, t["lang"], title=t["title"], concurrency=4,
                    progress=lambda done, total: store.update_run(
                        run_id, phase=f"claims {done}/{total}"),
                    on_batch=on_batch,
                )
            claims_list = extracted["claims"]
            tracing.flush()

            todo_ids = {c["hash"] for c in _select_for_verdicts(claims_list, MAX_VERDICTS_PER_RUN)}
            todo = len(todo_ids)
            # pay-per-use: машинные вердикты ограничены бюджетом установки
            paid = 0
            # СЕК-3: без install_id — анонимная квота (не безлимит); VFC_DEV_UNLIMITED=1 для разработки
            budget_left = (store.budget(install_id) if install_id else store.FREE_DAILY) \
                if _os.environ.get("VFC_DEV_UNLIMITED", "") != "1" else 10**9

            with tracing.span("verdicts", {"todo": todo}):
                # Слой 1 (ClaimReview) дешёвый — по всем отобранным. Слой 2 (sonar,
                # 10–20с на вердикт) получает предвыделенный бюджет: в пул уходит не
                # больше budget_left утверждений, воркеры бюджет не трогают — lock не нужен.
                need_sonar = []
                for c in claims_list:
                    if c["hash"] not in todo_ids:
                        store.save_claim(run_id, c, _with_meta(c, None))  # вне лимита прогона: без вердикта
                        continue
                    if c["hash"] in hit_hashes:
                        continue  # конвейер уже проверил (ClaimReview) и сохранил
                    human = factcheck_db.match(c["claim"], lang=verdict_lang or t["lang"])
                    if human:
                        store.save_claim(run_id, c, human)
                        checked += 1
                    elif len(need_sonar) < budget_left:
                        need_sonar.append(c)
                    else:
                        store.save_claim(run_id, c, _with_meta(c, None))  # бюджет установки исчерпан

                def run_sonar(c):
                    # язык обоснований — из настройки расширения; экстракция остаётся
                    # на языке транскрипта (утверждения цитируются в оригинале)
                    return verdict_mod.check(c["claim"], verdict_lang or t["lang"], title=t["title"])

                # Этап 2.5 — научное правдоподобие (косвенные свидетельства,:
                # бесплатно, гонится параллельно sonar (2 воркера), к моменту готовности
                # sonar-вердикта обычно уже есть. Прикрепляется к result как plausibility.
                plaus_futs: dict = {}
                plaus_pool = None
                if plaus_mod.enabled() and need_sonar:
                    plaus_pool = ThreadPoolExecutor(max_workers=2)
                    for c in need_sonar:
                        plaus_futs[c["hash"]] = plaus_pool.submit(
                            plaus_mod.check, c["claim"], verdict_lang or t["lang"])

                # Вердикты — по 3 одновременно: последовательный цикл был главным
                # боттлнеком прогона. Записи и счётчики ведёт только главный поток
                # (as_completed), воркеры лишь считают — общего изменяемого состояния нет.
                try:
                    with ThreadPoolExecutor(max_workers=3) as ex:
                        futures = {ex.submit(run_sonar, c): c for c in need_sonar}
                        finished = checked  # слой 1 уже посчитан; K = завершённые
                        for fut in as_completed(futures):
                            c = futures[fut]
                            try:
                                result = fut.result()
                                paid += 1
                                checked += 1
                            except Exception as sonar_err:  # noqa: BLE001 — один claim не валит всё
                                print(f"[pipeline:warn] sonar failed для {c['hash'][:8]}: {sonar_err}")
                                result = None
                            # косвенные научные свидетельства — в карточку вердикта
                            pf = plaus_futs.get(c["hash"])
                            if pf is not None:
                                try:
                                    p = pf.result(timeout=45)
                                    if p and result is not None:
                                        result = dict(result)
                                        result["plausibility"] = p
                                        # шаг 2 дилеммы: гварды прошли — наука
                                        # понижает конфликтный вердикт (не «ложно»)
                                        result = verdict_mod.fuse(result, verdict_lang or t["lang"])
                                except Exception:  # noqa: BLE001 — плозибилити не критична
                                    pass
                            store.save_claim(run_id, c, _with_meta(c, result))  # по мере готовности
                            finished += 1
                            store.update_run(run_id, phase=f"verdict {finished}/{todo}")
                finally:
                    if plaus_pool is not None:
                        plaus_pool.shutdown(wait=False)

            if install_id and paid:
                store.settle(install_id, paid)

            no_claims = len(claims_list) == 0
            store.update_run(
                run_id, status="done", phase="done",
                summary=_summary(run_id, t, claims_list, extracted["skipped"], checked,
                                 no_claims=no_claims))
            tracing.flush()
        except Exception as e:  # noqa: BLE001 — фоновый поток, ошибка уходит в статус
            store.update_run(run_id, status="error", error=_public_error(e))
            with tracing.span("error", {"error": str(e)[:300]}):
                pass
            tracing.flush()


def _with_meta(c: dict, result: dict | None) -> dict | None:
    """Метаданные экстракции (significance, числовые поля) — в JSON результата:
    так golden-экспорт и аналитика видят их из БД (риск 3 верификации 29.10)."""
    if result is None:
        result = {}
    meta = {k: c.get(k) for k in ("significance", "checkability_reason", "category",
                                  "subject", "indicator", "value_norm", "unit", "year")
            if c.get(k) is not None}
    if meta:
        result = {**result, "claim_meta": meta}
    return result or None


def _public_error(e: Exception) -> str:
    """СЕК-8: в статус уходит чистая причина, без stderr/путей/ключей; сырая — в лог сервера.
    Whitelist собственных RuntimeError-сообщений (ревью P1-4): подстрочный фильтр
    «yt-dlp» пропускал str(TimeoutExpired) с полной argv — включая креды прокси."""
    import sys
    raw = str(e)
    print(f"[pipeline:err] run failed: {raw[:500]}", file=sys.stderr)
    # собственные осмысленные сообщения транслируем как есть; всё чужое
    # (subprocess-исключения, traceback) — общий текст без деталей
    own_markers = ("Субтитры не скачались", "похоже на плейлист", "На видео нет субтитров",
                   "yt-dlp не отдал данные")
    if any(raw.startswith(m) or m in raw for m in own_markers) and "\n" not in raw:
        return raw[:300]
    return "проверка не удалась, подробности в логе сервера"


def _select_for_verdicts(claims: list[dict], k: int) -> list[dict]:
    """Лимит денег распределяем равномерно по таймлайну: у длинного видео
    проверенные утверждения должны покрывать весь ролик, а не первые минуты
    (находка логов 2026-10-28: 43-мин видео — все claims в 0–206с)."""
    if len(claims) <= k:
        return claims
    claims = sorted(claims, key=lambda c: c["t_start"])
    step = len(claims) / k
    idx = sorted({min(int(i * step), len(claims) - 1) for i in range(k)})
    return [claims[i] for i in idx]


def _summary(run_id: str, t: dict, claims_list: list[dict],
             skipped: list[dict], checked: int, no_claims: bool = False) -> dict:
    counts = {"правда": 0, "ложно": 0, "странно": 0, "не проверено": 0}
    with store.connect() as con:
        rows = con.execute(
            "SELECT verdict FROM claims WHERE run_id=? AND verdict IS NOT NULL",
            (run_id,),
        ).fetchall()
    for r in rows:
        counts[r["verdict"] if r["verdict"] in counts else "странно"] += 1
    counts["не проверено"] = max(0, len(claims_list) - checked)
    return {
        "title": t["title"], "video_id": t["video_id"], "duration": t["duration"],
        "lang": t["lang"], "sub_kind": t["sub_kind"],
        "claims_total": len(claims_list), "checked": checked,
        "skipped_opinions": len(skipped),
        "no_claims": no_claims,
        "counts": counts,
    }


def get_status(run_id: str) -> dict:
    with store.connect() as con:
        row = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return {"error": "run not found"}
    out: dict = {
        "run_id": run_id, "status": row["status"], "phase": row["phase"],
        "title": row["title"], "error": row["error"],
    }
    if row["summary"]:
        out["summary"] = json.loads(row["summary"])
    if row["status"] in ("done", "error") or row["phase"].startswith("verdict"):
        out["claims"] = store.load_claims(run_id)
    return out
