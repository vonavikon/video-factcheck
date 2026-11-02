"""Pipeline orchestrator: transcript → claims → (ClaimReview) → search → verdicts.

Stage 2 (ClaimReview) is enabled by VFC_FACTCHECK_KEY (Google Cloud; without a key
the layer is skipped). The extension receives status/verdicts via server.py.
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
    """Start the pipeline in the background. transcript is client-side (the extension
    read subtitles from the page, the user's IP); None → the server fetches it (yt-dlp).
    verdict_lang is the language of verdict justifications (the extension's
    "language" setting); None → the transcript language, as before."""
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
                t = transcript or tr.fetch(url)  # client-side subs come first: no 429
            store.update_run(run_id, title=t["title"], summary={
                "title": t["title"], "duration": t["duration"],
                "video_id": t["video_id"],
            })
            store.save_transcript(t)

            # Pipeline: ClaimReview is
            # free and instant, it checks claims as extraction batches finish,
            # not after extraction. The first "Проверено людьми" cards arrive
            # with the first batches. sonar stays after extraction:
            # its slots are distributed by timeline stratification (43-min feedback).
            hit_hashes: set[str] = set()
            checked = 0  # issued verdicts (by fact-checkers or sonar), goes into summary;
            # declared before on_batch: the pipeline increments it during extraction

            def on_batch(batch_claims) -> None:
                nonlocal checked
                vlang = verdict_lang or t["lang"]
                for c in batch_claims:
                    if c["hash"] in hit_hashes:
                        continue  # batches arrive pre-dedup; the same claim may come twice
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
            # pay-per-use: machine verdicts are capped by the installation budget
            paid = 0
            # SEC-3: without install_id, an anonymous quota (not unlimited); VFC_DEV_UNLIMITED=1 for development
            budget_left = (store.budget(install_id) if install_id else store.FREE_DAILY) \
                if _os.environ.get("VFC_DEV_UNLIMITED", "") != "1" else 10**9

            with tracing.span("verdicts", {"todo": todo}):
                # Layer 1 (ClaimReview) is cheap, runs on all selected claims. Layer 2 (sonar,
                # 10-20s per verdict) gets a pre-allocated budget: no more than
                # budget_left claims enter the pool, workers never touch the budget, no lock needed.
                need_sonar = []
                for c in claims_list:
                    if c["hash"] not in todo_ids:
                        store.save_claim(run_id, c, _with_meta(c, None))  # outside the run cap: no verdict
                        continue
                    if c["hash"] in hit_hashes:
                        continue  # the pipeline already checked it (ClaimReview) and saved it
                    human = factcheck_db.match(c["claim"], lang=verdict_lang or t["lang"])
                    if human:
                        store.save_claim(run_id, c, human)
                        checked += 1
                    elif len(need_sonar) < budget_left:
                        need_sonar.append(c)
                    else:
                        store.save_claim(run_id, c, _with_meta(c, None))  # installation budget exhausted

                def run_sonar(c):
                    # justification language comes from the extension setting; extraction stays
                    # in the transcript language (claims are quoted in the original)
                    return verdict_mod.check(c["claim"], verdict_lang or t["lang"], title=t["title"])

                # Stage 2.5, scientific plausibility (indirect evidence,
                # free), runs in parallel with sonar (2 workers) and is usually
                # done by the time the sonar verdict is ready. Attached to result as plausibility.
                plaus_futs: dict = {}
                plaus_pool = None
                if plaus_mod.enabled() and need_sonar:
                    plaus_pool = ThreadPoolExecutor(max_workers=2)
                    for c in need_sonar:
                        plaus_futs[c["hash"]] = plaus_pool.submit(
                            plaus_mod.check, c["claim"], verdict_lang or t["lang"])

                # Verdicts, 3 at a time: the sequential loop was the run's main
                # bottleneck. Writes and counters are owned by the main thread
                # (as_completed), workers only compute, no shared mutable state.
                try:
                    with ThreadPoolExecutor(max_workers=3) as ex:
                        futures = {ex.submit(run_sonar, c): c for c in need_sonar}
                        finished = checked  # layer 1 is already counted; K = completed
                        for fut in as_completed(futures):
                            c = futures[fut]
                            try:
                                result = fut.result()
                                paid += 1
                                checked += 1
                            except Exception as sonar_err:  # noqa: BLE001: one claim must not kill everything
                                print(f"[pipeline:warn] sonar failed для {c['hash'][:8]}: {sonar_err}")
                                result = None
                            # indirect scientific evidence, into the verdict card
                            pf = plaus_futs.get(c["hash"])
                            if pf is not None:
                                try:
                                    p = pf.result(timeout=45)
                                    if p and result is not None:
                                        result = dict(result)
                                        result["plausibility"] = p
                                        # dilemma step 2: guards passed, science
                                        # downgrades the conflicting verdict (not "ложно")
                                        result = verdict_mod.fuse(result, verdict_lang or t["lang"])
                                except Exception:  # noqa: BLE001: plausibility is not critical
                                    pass
                            store.save_claim(run_id, c, _with_meta(c, result))  # as they become ready
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
        except Exception as e:  # noqa: BLE001: background thread, the error goes into status
            store.update_run(run_id, status="error", error=_public_error(e))
            with tracing.span("error", {"error": str(e)[:300]}):
                pass
            tracing.flush()


def _with_meta(c: dict, result: dict | None) -> dict | None:
    """Extraction metadata (significance, numeric fields), into the result JSON:
    this way the golden export and analytics see them from the DB (verification risk 3, 29.10)."""
    if result is None:
        result = {}
    meta = {k: c.get(k) for k in ("significance", "checkability_reason", "category",
                                  "subject", "indicator", "value_norm", "unit", "year")
            if c.get(k) is not None}
    if meta:
        result = {**result, "claim_meta": meta}
    return result or None


def _public_error(e: Exception) -> str:
    """SEC-8: the status gets a clean reason, without stderr/paths/keys; the raw one goes to the server log.
    A whitelist of our own RuntimeError messages (review P1-4): the substring filter
    "yt-dlp" let through str(TimeoutExpired) with the full argv, including proxy credentials."""
    import sys
    raw = str(e)
    print(f"[pipeline:err] run failed: {raw[:500]}", file=sys.stderr)
    # our own meaningful messages pass through as is; everything else
    # (subprocess exceptions, tracebacks) gets a generic text without details
    own_markers = ("Субтитры не скачались", "похоже на плейлист", "На видео нет субтитров",
                   "yt-dlp не отдал данные")
    if any(raw.startswith(m) or m in raw for m in own_markers) and "\n" not in raw:
        return raw[:300]
    return "проверка не удалась, подробности в логе сервера"


def _select_for_verdicts(claims: list[dict], k: int) -> list[dict]:
    """The money budget is spread evenly across the timeline: for a long video the
    checked claims must cover the whole video, not the first minutes
    (log finding 2026-10-28: a 43-min video had all claims within 0-206s)."""
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
