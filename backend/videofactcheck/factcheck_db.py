"""Stage 2: matching against existing fact-checks (Google Fact Check Tools API / ClaimReview).

The first and cheapest verdict layer: if the claim has already been checked by humans
(Politifact, Snopes, AFP, «Проверено.медиа»), we show their verdict with the outlet's
attribution and no LLM involved at all. Decision B12 (live API; a local dump is planned for iteration 2).

Key: VFC_FACTCHECK_KEY (Google Cloud API key, starts with AIza). If the key is missing or
the API is unreachable, the layer is silently skipped and the sonar layer takes over.
"""
import os
import re
from urllib.parse import urlparse

import httpx

API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"  # v1.1 was removed by Google (404), v1alpha1 is current

# verbal fact-checker ratings → our three classes.
# Match on word start (\b), not substring: "сложно" must not match as "ложно".
# Order: mixed ratings first ("half true" contains "true", but it is not "правда").
RATING_RE = [
    ("странно", r"\bmixture\b|\bpartly\b|\bhalf[- ]true\b|\bmisleading\b|\bunproven\b|"
                r"\bчастичн\w*|\bвводит в заблуждение\b|\bнепровер\w*|\bнет данных\b"),
    ("ложно",   r"\bfalse\b|\bpants on fire\b|\bdistort\w*|\bложн\w*|\bложь\b|"
                r"\bфейк\w*|\bманипуляц\w*"),
    ("правда",  r"\btrue\b|\bcorrect\b|\baccurate\b|\bправд\w*|\bверн\w*|\bподтвержд\w*"),
]


def _map_rating(rating: str) -> tuple[str, str]:
    """Verbal outlet rating → (правда/ложно/странно, note)."""
    r = (rating or "").lower()
    for verdict, pattern in RATING_RE:
        if re.search(pattern, r):
            return verdict, ""
    # unfamiliar outlet scale: show as is, classify cautiously
    return "странно", f"оригинальный вердикт: «{rating}»"


def match(claim: str, lang: str = "ru") -> dict | None:
    """Claim → verdict from ClaimReview with attribution, or None (layer skipped).
    lang is the language of why (ru/en), taken from the extension setting (review P1-5)."""
    key = os.environ.get("VFC_FACTCHECK_KEY", "").strip()
    if not key:
        return None
    try:
        r = httpx.get(API, params={"key": key, "query": claim[:180], "pageSize": 5},
                      timeout=15.0)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:  # noqa: BLE001: optional layer, a failure does not break the pipeline
        return None

    best = None
    best_sim = 0.0
    for c in data.get("claims", []):
        reviewed = c.get("text") or c.get("claimText") or ""
        sim = _similarity(claim, reviewed)
        if sim > best_sim:
            best_sim = sim
            best = c
    if not best or best_sim < 0.45:
        return None

    review = (best.get("claimReview") or [{}])[0]
    rating = (review.get("textualRating") or "").strip()
    publisher = ((review.get("publisher") or {}).get("name") or "").strip()
    url = (review.get("url") or "").strip()
    verdict, note = _map_rating(rating)
    domain = urlparse(url).netloc.removeprefix("www.") if url else publisher
    # why localization: an en user sees English cards next to sonar counterparts
    if lang == "en":
        why = (f"Checked by human fact-checkers ({publisher}): “{rating}”" if rating
               else f"Checked by human fact-checkers ({publisher})")
    else:
        why = (f"Проверено людьми ({publisher}): «{rating}»" if rating
               else f"Проверено людьми ({publisher})")
    return {
        "verdict": verdict,
        "why": f"{why}{'; ' + note if note else ''}",
        "votes": [{
            "domain": domain or publisher, "url": url,
            "title": review.get("title") or "",
            "quote": f"Вердикт факт-чекера: {rating}" if rating else "",
            "trust": 0.9,  # professional fact-check
        }],
        "relevant": 1,
        "confidence": "высокая",  # verdict issued by a human fact-checker
        "engine": "claimreview",
        "passes": ["human"],
        "similarity": round(best_sim, 2),
    }




def _similarity(a: str, b: str) -> float:
    """Normalized token intersection (containment: |A∩B|/min(|A|,|B|))."""
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    return len(inter) / min(len(ta), len(tb))


def _tokens(t: str) -> set[str]:
    t = re.sub(r"[^\wа-яё\s]", " ", t.lower())
    stop = {"в", "на", "и", "the", "a", "of", "is", "что", "для", "to", "in", "по"}
    return {w for w in t.split() if len(w) > 2 and w not in stop}
