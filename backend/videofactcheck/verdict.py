"""Stages 3-4 (merged): search + verdict via Perplexity sonar (bothub).

Sonar runs web search on its side and answers with cited sources, so no
external search API is needed (Bing degrades without JS, DDG blocks
requests, Google requires JS; recorded in docs/decisions.md).

Two sonar passes (search is non-deterministic, the passes genuinely differ);
when the verdicts disagree the result is «странно». A verbatim quote per
source is mandatory. The Evidence Verification layer (verify.py) matches
quotes of the top sources against the original page: "not_found" (paraphrase
or fabrication) removes the source.
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

# why-language substitution: verdict values («правда» etc.) stay Russian:
# internal contract of the server, the client translates them for display (verdictLabel)
LANG_WHY = {
    "ru": "why: одно предложение на русском для показа пользователю",
    "en": "why: one sentence in English for the user; verdict values stay Russian",
}


def check(claim: str, lang: str = "ru", passes: int = 2, title: str = "") -> dict:
    """Claim -> verdict with sources. Two sonar passes, disagreement -> «странно».
    lang sets the language of the why rationale (ru/en); verdict values are always Russian."""
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
        except Exception:  # noqa: BLE001 - broken JSON = failed pass
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
    """Verdict confidence level (user feedback).

    Honest levels instead of pseudo-precise percentages (research: a single
    score is unvalidated; FactScore: even GPT-4 errs on ~27% of atomic facts).
    Formula:
      base 0.6: both sonar passes agreed on the verdict (disagreement -> «странно»)
      +0.25: >=2 sources with quotes and average trust >=0.7  -> «высокая»
      +0.15: sources exist with average trust >=0.5           -> «средняя»
      -0.05: only weak sources (average <0.5)
      -0.15: no sources at all
    result: >=0.8 «высокая», >=0.6 «средняя», otherwise «низкая».
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
    """Only http(s) with a valid domain: guards against javascript: injections from LLM output."""
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
    """Sources of the best pass (the first non-empty list), weighted by domain trust.

    The quote rule enforced in code, not only in the prompt: a source without
    a verbatim quote is dropped (the model could have invented it).
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
            continue  # javascript:/junk schemes from the LLM are not sources
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
    """Science influence on the verdict: step 2 of the dilemma (docs/verdict-math.md).

    Guards are already computed in plausibility.influential (verbatim quote +
    directly_on_topic + year >= 2015 or a review/meta-analysis). Epistemics:
    science NEVER issues «ложно»; a conflict with sonar demotes the verdict
    to «странно» with confidence «низкая» and a glued rationale. A
    «правда»+supports return does not raise confidence until calibration on
    a golden set (a future iteration of the Bayesian accumulator).
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
