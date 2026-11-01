"""Stages 3–4 (merged): search + verdict via Perplexity sonar (bothub).

Sonar runs web search on its side and answers with source citations —
no external search API needed (Bing degrades without JS, DDG blocks bots,
Google requires JS; decision recorded in В14).

Two sonar passes (search is non-deterministic — the passes really differ);
verdict disagreement → "странно" (В16). A quote is mandatory (В18).
"""
import os

from . import llm
from .trust import domain_trust

VERDICTS = ("правда", "ложно", "странно")
SONAR_MODEL = os.environ.get("VFC_SONAR_MODEL", "sonar")

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

# justification language substitution: verdict values ("правда"…) stay Russian —
# this is the server's internal contract, the client translates for display (verdictLabel)
LANG_WHY = {
    "ru": "why: одно предложение на русском для показа пользователю",
    "en": "why: one sentence in English for the user; verdict values stay Russian",
}


def check(claim: str, lang: str = "ru", passes: int = 2, title: str = "") -> dict:
    """Claim → verdict with sources. Two sonar passes, disagreement → "странно".
    lang sets the language of why (ru/en); verdict values are always Russian."""
    ctx = f"\nКонтекст: утверждение из видео «{title}»." if title else ""
    prompt = PROMPT.replace(
        "why: одно предложение на русском для показа пользователю",
        LANG_WHY.get(lang, LANG_WHY["ru"]))
    verdicts, whys, sources_by_pass = [], [], []
    for _ in range(passes):
        text = llm.chat(
            [{"role": "system", "content": prompt + ctx},
             {"role": "user", "content": f"УТВЕРЖДЕНИЕ: {claim}"}],
            model=SONAR_MODEL, json_mode=False, max_tokens=3000,  # sonar: text mode only
        )
        try:
            data = llm.parse_json(text)
        except Exception:  # noqa: BLE001 — broken JSON = failed pass
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

    votes = _votes(sources_by_pass)
    return _result(final, why, votes, verdicts)


def _confidence(passes: list[str], votes: list[dict]) -> str:
    """Verdict confidence level (feedback item 5).

    Honest levels instead of pseudo-precise percentages (research: a single score
    is unvalidated; FactScore: even GPT-4 gets ~27% of atomic facts wrong).
    Formula:
      base 0.6 — both sonar passes agreed on the verdict (disagreement → "странно")
      +0.25   — ≥2 sources with quotes and average trust ≥0.7    → "высокая"
      +0.15   — sources exist with average trust ≥0.5            → "средняя"
      −0.05   — only weak sources (average <0.5)
      −0.15   — no sources at all
    result: ≥0.8 "высокая", ≥0.6 "средняя", otherwise "низкая".
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
    """http(s) and a valid domain only: protection against javascript: injections via the LLM (СЕК-1)."""
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
    """Sources of the best pass (the first with a non-empty list), with trust weights.

    Rule В18 enforced in code, not just in the prompt: a source without a verbatim
    quote is not included (the model could have invented it).
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
            continue  # javascript:/garbage schemes from the LLM are not sources
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
    """Science's influence on the verdict — step 2 of the dilemma.

    Guards are already computed in plausibility.influential (verbatim quote +
    directly_on_topic + year ≥ 2015 or a review/meta-analysis). Epistemics:
    science NEVER issues "ложно" — a conflict with sonar downgrades the verdict
    to "странно" with confidence "низкая" and a glued justification.
    A "правда"+supports return does not raise confidence until calibrated
    on the golden set (a future bayesian-accumulator iteration).
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
