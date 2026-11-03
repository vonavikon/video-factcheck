"""Stage 2.5: plausibility check against scientific databases (docs/verdict-math.md).

Indirect evidence: direct fact-checks of niche claims do not exist and never
will, but a claim can clash with established scientific knowledge (design
example: "a diploma in 72 hours" vs sleep-deprivation science). Sources are
Europe PMC (medicine/biology, full abstracts, no key) and OpenAlex (all of
science, a key multiplies the limits x10). Adjudication is a cheap deepseek
NLI over the top-3 abstracts with a mandatory verbatim quote.

Epistemic rule: indirect evidence NEVER yields «ложно». Relation "refutes"
is shown as a separate status "scientific evidence: contradicts" next to the
sonar verdict, not instead of it.

The layer is free for the user (only sonar spends credits) and optional:
any error -> None, the pipeline is unaffected.
"""
import json
import os

import httpx

from . import llm
from .verify import quote_in_text

PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX_API = "https://api.openalex.org/works"

ADJUDICATE_PROMPT = """Ты — научный рецензент. Дано утверждение из видео и абстракты \
научных статей. Определи отношение устоявшегося научного знания к утверждению.

Правила:
- relation: "refutes" | "supports" | "insufficient"
- "refutes" = научные данные делают утверждение маловероятным. Это КОСВЕННОЕ \
свидетельство: прямых факт-чеков утверждения может не быть, но оно противоречит \
устоявшемуся знанию. Терминологические неточности — не refutes.
- "supports" = научные данные подтверждают суть утверждения
- "insufficient" = абстракты не по теме утверждения или пусты
- relevance: насколько абстракт-цитата исследует ИМЕННО это утверждение:
  "directly_on_topic" = тот же объект/воздействие и тот же исход (препарат в той \
же форме, та же популяция, то же следствие); "adjacent" = смежная тема (другая \
форма препарата, другая популяция, другой исход, обзор про другое); \
"off" = мимо темы
- why: одно предложение на языке {LANG} для показа пользователю
- quote: ДОСЛОВНАЯ цитата из абстракта с номером {N}, подтверждающая вывод; \
без подходящей цитаты — relation обязателен "insufficient"
- article: номер абстракта (0-based), из которого цитата
- отвечай ТОЛЬКО JSON: \
{"relation":"...","relevance":"...","why":"...","quote":"...","article":0}"""


def enabled() -> bool:
    """The layer is on by default; VFC_PLAUSIBILITY=0 disables it (cost/debugging)."""
    return os.environ.get("VFC_PLAUSIBILITY", "1").strip() != "0"


def _en_query(claim: str, lang: str) -> str:
    """Search query in English: science is published in English.
    For a ru claim one cheap call: reformulate it into an EN search query."""
    if lang == "en":
        return claim
    try:
        out = llm.chat(
            [{"role": "system", "content": "Переведи утверждение в короткий англоязычный "
                                           "поисковый запрос для научной базы (тема + объект, "
                                           "без лишних слов). Ответь только запросом."},
             {"role": "user", "content": claim}],
            max_tokens=3000, temperature=0.0)
        return (out or "").strip().strip('"')[:200] or claim
    except Exception:  # noqa: BLE001 - the layer is optional
        return claim


def _pmc(query: str) -> list[dict]:
    try:
        r = httpx.get(PMC_API, params={"query": query, "format": "json",
                                       "pageSize": 5, "resultType": "core"},
                      timeout=12.0)
        if r.status_code != 200:
            return []
        out = []
        for a in (r.json().get("resultList") or {}).get("result", []):
            ab = (a.get("abstractText") or "").strip()
            if len(ab) < 120:  # empty/truncated abstracts are useless for NLI
                continue
            pmid = a.get("pmid") or a.get("doi") or ""
            url = (f"https://europepmc.org/article/{a.get('source', 'MED')}/{pmid}"
                   if pmid else "")
            # pubTypeList.pubType: ["Review", "review-article", "Meta-Analysis", ...]
            ptypes = [str(x).lower() for x in
                      ((a.get("pubTypeList") or {}).get("pubType") or [])]
            kind = ("meta" if any("meta-analy" in x for x in ptypes)
                    else "review" if any("review" in x for x in ptypes) else "primary")
            out.append({"title": (a.get("title") or "")[:160],
                        "abstract": ab[:1400], "year": a.get("pubYear") or "",
                        "url": url, "kind": kind})
        return out[:3]
    except Exception:  # noqa: BLE001
        return []


def _openalex(query: str) -> list[dict]:
    key = os.environ.get("VFC_OPENALEX_KEY", "").strip()
    params = {"search": query, "per-page": 5}
    if key:
        params["api_key"] = key
    try:
        r = httpx.get(OPENALEX_API, params=params, timeout=12.0)
        if r.status_code != 200:
            return []
        out = []
        for w in (r.json() or {}).get("results", []):
            inv = w.get("abstract_inverted_index")
            if not inv:
                continue
            # inverted index -> text: word -> list of positions
            words: dict[int, str] = {}
            for word, positions in inv.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words[i] for i in sorted(words))[:1400]
            if len(abstract) < 120:
                continue
            url = w.get("doi") or (w.get("id") or "").replace("https://api.",
                                                              "https://.")
            out.append({"title": (w.get("display_name") or w.get("title") or "")[:160],
                        "abstract": abstract, "year": str(w.get("publication_year") or ""),
                        "url": url,
                        "kind": "review" if w.get("type") == "review" else "primary"})
        return out[:3]
    except Exception:  # noqa: BLE001
        return []


def _cjk(text: str) -> bool:
    """CJK leak: deepseek occasionally answers in Chinese despite the prompt language
    (live case 2026-10-29: a Chinese why in a minoxidil run)."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def check(claim: str, lang: str = "ru") -> dict | None:
    """Claim -> scientific plausibility verdict, or None (the layer stayed silent).

    Returns {relation, why, quote, source: {title, url, year}}.
    relation "refutes" means "unlikely per scientific data" (never «ложно»).
    """
    if not claim.strip():
        return None
    try:
        query = _en_query(claim, lang)
        articles = _pmc(query) or _openalex(query)
        if not articles:
            return None
        corpus = "\n\n".join(
            f"АБСТРАКТ {i}: {a['title']} ({a['year']})\n{a['abstract']}"
            for i, a in enumerate(articles))
        prompt = (ADJUDICATE_PROMPT.replace("{LANG}", "русском" if lang == "ru" else "English")
                  .replace("{N}", "0-" + str(len(articles) - 1)))
        # why must be in the user's language: a Chinese answer is retried, up to
        # 3 attempts; a persistent leak means the layer stays silent (None)
        data: dict = {}
        for attempt in range(3):
            raw = llm.chat(
                [{"role": "system", "content": prompt + ("\nОТВЕТ СТРОГО НА РУССКОМ ЯЗЫКЕ."
                                                        if attempt and lang != "en" else "")},
                 {"role": "user", "content": f"УТВЕРЖДЕНИЕ: {claim}\n\n{corpus}"}],
                json_mode=True, max_tokens=4000, temperature=0.0)
            data = llm.parse_json(raw)
            if not _cjk((data.get("why") or "")):
                break
        relation = data.get("relation")
        if relation not in ("refutes", "supports", "insufficient"):
            return None
        if _cjk((data.get("why") or "")):
            return None  # showing Chinese text to the user is worse than staying silent
        # step-2 guards (docs/verdict-math.md): science affects the verdict only
        # with a verbatim quote (the quote rule above), DIRECT relevance and
        # freshness (year >= 2015 or a review/meta-analysis). A relation without
        # a quote is already dropped; cautious default: no relevance from the
        # NLI = treat as adjacent
        relevance = data.get("relevance")
        if relevance not in ("directly_on_topic", "adjacent", "off"):
            relevance = "adjacent"
        idx = data.get("article")
        src = articles[idx] if isinstance(idx, int) and 0 <= idx < len(articles) else articles[0]
        quote = (data.get("quote") or "").strip()
        if relation != "insufficient" and not quote:
            return None  # without a verbatim quote the conclusion does not count (quote rule)
        # Evidence Verification, local corpus: the quote must actually occur
        # in the cited abstract (the rule enforced in code, not only in the
        # prompt). A quote not found in the abstract we hold in hand =
        # fabrication -> the whole NLI answer is untrustworthy -> the layer
        # stays silent (None).
        if quote and not quote_in_text(quote, src["abstract"]):
            return None
        try:
            src_yr = int(str(src.get("year") or "0"))
        except ValueError:
            src_yr = 0
        influential = (relation in ("refutes", "supports")
                       and relevance == "directly_on_topic"
                       and (src_yr >= 2015 or src.get("kind") in ("review", "meta")))
        return {
            "relation": relation,
            "relevance": relevance,
            "influential": influential,
            "why": (data.get("why") or "").strip()[:300],
            "quote": quote[:400],
            "source": {"title": src["title"], "url": src["url"], "year": src["year"],
                       "kind": src.get("kind", "primary")},
        }
    except Exception:  # noqa: BLE001 - the layer is optional: any error = silence
        return None
