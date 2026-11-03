"""Этапы 3–4 (объединены): поиск + вердикт через Perplexity sonar (bothub).

Sonar делает веб-поиск на своей стороне и отвечает с цитатами-источниками —
внешний поисковый API не нужен (Bing без JS деградирует, DDG блокируется,
Google требует JS; решение зафиксировано в docs/decisions.md, В14).

Два прохода sonar (поиск недетерминирован — проходы реально разные);
расхождение вердиктов → «странно» (В16). Цитата обязательна (В18).
Слой Evidence Verification (verify.py): цитаты топ-источников сверяются
со страницей-оригиналом — «not_found» (парафраз/выдумка) удаляет источник.
"""
import os
from concurrent.futures import ThreadPoolExecutor, wait

from . import llm
from . import verify
from .trust import domain_trust

VERDICTS = ("правда", "ложно", "странно")
SONAR_MODEL = os.environ.get("VFC_SONAR_MODEL", "sonar")
VERIFY_TOP = 2          # only top sources by trust get fetched — latency budget
VERIFY_BUDGET_S = 10.0  # hard ceiling for the whole verification layer

PROMPT = """Ты — факт-чекер с доступом к веб-поиску. Проверь утверждение из видео \
по актуальным источникам и вынеси вердикт.

Правила:
- verdict: "правда" | "ложно" | "странно"
- "странно" = insufficient data: источников нет, они противоречивы или слабы
- терминологические неточности и упрощения, не меняющие сути утверждения, \
не делают его «ложно» — это «правда» с уточнением в why; «ложно» только когда \
суть утверждения опровергнута (не та цифра, не тот факт, событие не было)
- why: одно предложение на русском для показа пользователю
- sources: 1–4 лучших источника, у каждого ДОСЛОВНАЯ цитата quote, подтверждающая \
вердикт (не выдумывай цитаты); без цитаты источник не приводи
- утверждение могло быть верным на момент записи видео — если источники новее \
и противоречат, отметь это в why
- отвечай ТОЛЬКО JSON: \
{"verdict":"...","why":"...","sources":[{"title":"...","url":"...","quote":"..."}]}
"""

# подстановка языка обоснования: значения verdict («правда»…) остаются русскими —
# это внутренний контракт сервера, клиент переводит на выводе (verdictLabel)
LANG_WHY = {
    "ru": "why: одно предложение на русском для показа пользователю",
    "en": "why: one sentence in English for the user; verdict values stay Russian",
}


def check(claim: str, lang: str = "ru", passes: int = 2, title: str = "") -> dict:
    """Утверждение → вердикт с источниками. Два прохода sonar, расхождение → «странно».
    lang задаёт язык обоснования why (ru/en); значения verdict всегда русские."""
    ctx = f"\nКонтекст: утверждение из видео «{title}»." if title else ""
    prompt = PROMPT.replace(
        "why: одно предложение на русском для показа пользователю",
        LANG_WHY.get(lang, LANG_WHY["ru"]))
    verdicts, whys, sources_by_pass = [], [], []
    for _ in range(passes):
        text = llm.chat(
            [{"role": "system", "content": prompt + ctx},
             {"role": "user", "content": f"УТВЕРЖДЕНИЕ: {claim}"}],
            model=SONAR_MODEL, json_mode=False, max_tokens=3000,  # sonar: только text-режим
        )
        try:
            data = llm.parse_json(text)
        except Exception:  # noqa: BLE001 — битый JSON = непроход
            verdicts.append("странно")
            whys.append("Модель вернула нечитаемый ответ")
            sources_by_pass.append([])
            continue
        v = data.get("verdict", "странно")
        verdicts.append(v if v in VERDICTS else "странно")
        whys.append(data.get("why", ""))
        sources_by_pass.append(data.get("sources", []) or [])

    if len(set(verdicts)) > 1:
        final, why = "странно", "Проходы разошлись: " + " / ".join(verdicts)
    else:
        final = verdicts[0]
        why = whys[0] or whys[-1]

    votes = _verify_votes(_votes(sources_by_pass))
    return _result(final, why, votes, verdicts)


def _verify_votes(votes: list[dict]) -> list[dict]:
    """Evidence Verification: match source quotes against original pages.

    "not_found" (likely paraphrase/fabrication — README: made-up quotes get
    filtered out) removes the source from votes. "unreachable" keeps it with
    a flag: a network failure is not the source's fault. Only top-VERIFY_TOP
    by trust are fetched; quotes shorter than verify.MIN_QUOTE_CHARS are
    "skipped" too (fuzzy matching on tiny strings is noise). Emptying votes
    lowers confidence via the regular formula — the verdict itself stands.
    """
    if not votes:
        return votes
    for v in votes:
        v["verify"] = "skipped"
    if not verify.enabled():
        return votes
    order = sorted(range(len(votes)), key=lambda i: votes[i]["trust"], reverse=True)
    todo = [i for i in order[:VERIFY_TOP]
            if len(votes[i]["quote"]) >= verify.MIN_QUOTE_CHARS]
    if not todo:
        return votes
    ex = ThreadPoolExecutor(max_workers=VERIFY_TOP)
    try:
        futs = {ex.submit(verify.verify_source, votes[i]["url"], votes[i]["quote"]): i
                for i in todo}
        done, _not_done = wait(futs, timeout=VERIFY_BUDGET_S)
        for f in done:
            try:
                votes[futs[f]]["verify"] = f.result()
            except Exception:  # noqa: BLE001 — verification must never kill the verdict
                pass
    finally:
        ex.shutdown(wait=False)  # honour the budget even if a worker hangs in DNS
    return [v for v in votes if v["verify"] != "not_found"]


def _confidence(passes: list[str], votes: list[dict]) -> str:
    """Уровень уверенности вердикта (пункт-5-фидбек).

    Честные уровни вместо псевдоточных процентов (исследование: единый скор
    невалидирован; FactScore: даже GPT-4 ошибается в ~27% атомарных фактов).
    Формула:
      база 0.6 — оба прохода sonar сошлись на вердикте (разошлись → «странно»)
      +0.25   — ≥2 источника с цитатами и средним доверием ≥0.7  → «высокая»
      +0.15   — есть источники со средним доверием ≥0.5           → «средняя»
      −0.05   — только слабые источники (среднее <0.5)
      −0.15   — источников нет вовсе
    итог: ≥0.8 «высокая», ≥0.6 «средняя», иначе «низкая».
    """
    if len(set(passes)) > 1:
        return "низкая"
    rel = votes
    n = len(rel)
    avg_t = sum(v["trust"] for v in rel) / n if n else 0.0
    score = 0.6
    if n >= 2 and avg_t >= 0.7:
        score += 0.25
    elif n >= 1 and avg_t >= 0.5:
        score += 0.15
    elif n >= 1:
        score -= 0.05
    else:
        score -= 0.15
    return "высокая" if score >= 0.8 else "средняя" if score >= 0.6 else "низкая"


def _safe_url(url: str) -> str | None:
    """Только http(s) и валидный домен: защита от javascript:-инъекций через LLM (СЕК-1)."""
    from urllib.parse import urlparse
    import re
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return None
        if not re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", p.netloc):
            return None
        return p.geturl()
    except Exception:
        return None


def _votes(sources_by_pass: list[list[dict]]) -> list[dict]:
    """Источники лучшего прохода (первого с непустым списком), с весом доверия.

    Правило В18 в коде, а не только в промпте: источник без дословной цитаты
    не приводится (модель могла его выдумать).
    """
    best = next((s for s in sources_by_pass if s), [])
    votes, seen = [], set()
    for s in best:
        url = (s.get("url") or "").strip()
        quote = (s.get("quote") or "").strip()
        if not url or not quote or url in seen:
            continue
        url = _safe_url(url)
        if not url:
            continue  # javascript:/мусорные схемы от LLM — не источник
        domain = url.split("/")[2].lower().removeprefix("www.") if "/" in url else ""
        if not domain:
            continue
        seen.add(url)
        votes.append({
            "domain": domain, "url": url,
            "title": (s.get("title") or "")[:120],
            "quote": (s.get("quote") or "").strip()[:300],
            "trust": domain_trust(domain),
        })
    return votes


def _result(verdict: str, why: str, votes: list[dict], passes: list[str]) -> dict:
    return {
        "verdict": verdict,
        "why": why,
        "votes": votes,
        "relevant": len(votes),
        "confidence": _confidence(passes, votes),
        "engine": f"sonar x{len(passes)}",
        "passes": passes,
    }


def fuse(result: dict, lang: str = "ru") -> dict:
    """Влияние науки на вердикт — шаг 2 дилеммы (docs/verdict-math.md).

    Гварды уже посчитаны в plausibility.influential (дословная цитата +
    directly_on_topic + год ≥ 2015 либо обзор/мета-анализ). Эпистемика:
    наука НИКОГДА не выносит «ложно» — конфликт с sonar понижает вердикт
    до «странно» с уверенностью «низкая» и склееным обоснованием.
    Возврат «правда»+supports не повышает уверенность до калибровки на
    золотом наборе (будущая итерация байес-аккумулятора).
    """
    p = (result or {}).get("plausibility") or {}
    if not p.get("influential"):
        return result
    v = result.get("verdict")
    ru = lang != "en"
    glue = {
        ("правда", "refutes"): (" Но научные данные противоречат: ",
                                " But scientific evidence contradicts this: "),
        ("ложно", "supports"): (" Научные данные подтверждают: ",
                                " Scientific evidence supports this: "),
    }
    if (v, p.get("relation")) not in glue:
        return result
    join, join_en = glue[(v, p["relation"])]
    out = dict(result)
    out["verdict_raw"] = v
    out["verdict"] = "странно"
    out["why"] = ((result.get("why") or "").strip() + (join if ru else join_en)
                  + (p.get("why") or "").strip()).strip()
    out["confidence"] = "низкая"
    out["science_flip"] = p["relation"]
    return out
