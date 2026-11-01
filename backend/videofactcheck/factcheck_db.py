"""Этап 2: матчинг с готовыми факт-чеками (Google Fact Check Tools API / ClaimReview).

Первый и самый дешёвый слой вердиктов: если утверждение уже проверялось людьми
(Politifact, Snopes, AFP, «Проверено.медиа»), показываем их вердикт с атрибуцией
издания — LLM не зовётся вовсе. Решение В12 (live API; локальный дамп — итерация 2).

Ключ VFC_FACTCHECK_KEY (Google Cloud API key, начинается с AIza). Ключа нет или
API недоступен — слой молча пропускается, работает sonar-слой.
"""
import os
import re
from urllib.parse import urlparse

import httpx

API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"  # v1.1 удалён Google (404), актуален v1alpha1

# словесные рейтинги факт-чекеров → наши три класса.
# Матчинг по началу слова (\b), не подстрокой: «сложно» не должно ловиться как «ложно».
# Порядок: сначала смешанные («half true» содержит «true», но это не правда).
RATING_RE = [
    ("странно", r"\bmixture\b|\bpartly\b|\bhalf[- ]true\b|\bmisleading\b|\bunproven\b|"
                r"\bчастичн\w*|\bвводит в заблуждение\b|\bнепровер\w*|\bнет данных\b"),
    ("ложно",   r"\bfalse\b|\bpants on fire\b|\bdistort\w*|\bложн\w*|\bложь\b|"
                r"\bфейк\w*|\bманипуляц\w*"),
    ("правда",  r"\btrue\b|\bcorrect\b|\baccurate\b|\bправд\w*|\bверн\w*|\bподтвержд\w*"),
]


def _map_rating(rating: str) -> tuple[str, str]:
    """Словесный рейтинг издания → (правда/ложно/странно, пояснение)."""
    r = (rating or "").lower()
    for verdict, pattern in RATING_RE:
        if re.search(pattern, r):
            return verdict, ""
    # незнакомая шкала издания — показываем как есть, классифицируем осторожно
    return "странно", f"оригинальный вердикт: «{rating}»"


def match(claim: str, lang: str = "ru") -> dict | None:
    """Утверждение → вердикт из ClaimReview с атрибуцией, либо None (слой пропущен).
    lang — язык why (ru/en), пришёл из настройки расширения (ревью P1-5)."""
    key = os.environ.get("VFC_FACTCHECK_KEY", "").strip()
    if not key:
        return None
    try:
        r = httpx.get(API, params={"key": key, "query": claim[:180], "pageSize": 5},
                      timeout=15.0)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:  # noqa: BLE001 — слой необязательный, отказ не роняет пайплайн
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
    # локализация why: en-пользователь видит английские карточки рядом с sonar-аналогами
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
            "trust": 0.9,  # профессиональный факт-чек
        }],
        "relevant": 1,
        "confidence": "высокая",  # вердикт вынесен человеком-факт-чекером
        "engine": "claimreview",
        "passes": ["human"],
        "similarity": round(best_sim, 2),
    }




def _similarity(a: str, b: str) -> float:
    """Нормализованное пересечение токенов (containment: |A∩B|/min(|A|,|B|))."""
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
