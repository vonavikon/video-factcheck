r"""Stage 2: matching against ready-made fact checks (Google Fact Check Tools API / ClaimReview).

The first and cheapest verdict layer: if a claim was already checked by humans
(Politifact, Snopes, AFP, «Проверено.медиа»), we show their verdict with the
publisher's attribution, no LLM call at all (decision: live API; a local dump
is a later iteration).

The key is VFC_FACTCHECK_KEY (Google Cloud API key, starts with AIza). Without
the key, or when the API is down, the layer is silently skipped and the sonar
layer does the work.

False-match guards (code-review fix): token similarity is blind to short
numbers ("на 20%" vs "на 30%": the "20" token is under 3 chars and dropped by
_tokens) and to polarity inversions ("препарат снижает риск на 20%" vs
"препарат увеличивает риск на 20%" scores 0.75). Every candidate therefore
passes two hard filters before similarity decides: (1) the number multisets of
the claim and the reviewed text must be equal; percentages are tracked separately
from absolutes (20% != 20), scale words folded into the value ("1,5 млн" ==
"1500000"), texts where one side has numbers and the other has none mismatch
too; (2) direction antonyms (RU+EN, matched by word-boundary stems so Russian
morphology is covered: снижается/снизили/снижение -> \bсни[зж]\w*) must not
point opposite ways in the two texts, and a negated direction («не
увеличивает», "does not increase") conflicts with any plain direction in the
other text. Both guards are deliberately conservative:
a mismatch discards the candidate and the claim falls through to the sonar
layer: a false reject costs one LLM call, while a false match would pin a
human verdict (trust 0.9, confidence "высокая") on a claim the fact-checker
never made.

Known limitations (accepted, conservative): word numerals («двадцать
процентов») and number ranges («от 20 до 30%») are not extracted; space-
grouped thousands («1 000») parse as two numbers.
"""
import os
import re
from collections import Counter
from urllib.parse import urlparse

import httpx

API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"  # v1.1 was removed by Google (404), v1alpha1 is the live one

# Verbal ratings of fact-checkers → our three classes.
# Matching by word start (\b), not by substring: «сложно» must not match as «ложно».
# Order: mixed ratings first ("half true" contains "true", but it is not true).
RATING_RE = [
    ("странно", r"\bmixture\b|\bpartly\b|\bhalf[- ]true\b|\bmisleading\b|\bunproven\b|"
                r"\bчастичн\w*|\bвводит в заблуждение\b|\bнепровер\w*|\bнет данных\b"),
    ("ложно",   r"\bfalse\b|\bpants on fire\b|\bdistort\w*|\bложн\w*|\bложь\b|"
                r"\bфейк\w*|\bманипуляц\w*"),
    ("правда",  r"\btrue\b|\bcorrect\b|\baccurate\b|\bправд\w*|\bверн\w*|\bподтвержд\w*"),
]


def _map_rating(rating: str) -> tuple[str, str]:
    """A publisher's verbal rating → (правда/ложно/странно, note)."""
    r = (rating or "").lower()
    for verdict, pattern in RATING_RE:
        if re.search(pattern, r):
            return verdict, ""
    # unknown publisher scale: show as is, classify conservatively
    return "странно", f"оригинальный вердикт: «{rating}»"


def match(claim: str, lang: str = "ru") -> dict | None:
    """A claim → a ClaimReview verdict with attribution, or None (layer skipped).
    lang is the why language (ru/en), it comes from the extension setting."""
    key = os.environ.get("VFC_FACTCHECK_KEY", "").strip()
    if not key:
        return None
    try:
        r = httpx.get(API, params={"key": key, "query": claim[:180], "pageSize": 5},
                      timeout=15.0)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:  # noqa: BLE001: the layer is optional, a failure does not kill the pipeline
        return None

    best = None
    best_sim = 0.0
    for c in data.get("claims", []):
        reviewed = c.get("text") or c.get("claimText") or ""
        sim = _similarity(claim, reviewed)
        # Guards are hard filters, not tie-breakers: a candidate contradicting
        # the claim on numbers or direction is discarded even at top similarity,
        # and the claim falls through to the next candidate or the sonar layer.
        if sim > best_sim and _guards_pass(claim, reviewed):
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


# --- Guards against false matches ---------------------------------------------
# Numbers: comma-grouped thousands go first ("1,000" is 1000, not the decimal
# 1.0), then the plain/decimal branch. The unit may be separated by spaces
# (incl. nbsp) or glued; percentage points («процентных пунктов», «п.п.») must
# be listed before the bare «процент» branch, or the alternation stops early.
_NUM_RE = re.compile(
    r"""
    (?P<num>\d{1,3}(?:,\d{3})+|\d+(?:[.,]\d+)?)
    \s*
    (?P<unit>процентн\w*\s+пункт\w*|п\.\s*п\.|%|процент\w*|миллион\w*|миллиард\w*|млн\b|млрд\b|тысяч\w*|тыс\b|thousand|million|billion)?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_GROUPED_RE = re.compile(r"\d{1,3}(?:,\d{3})+")  # "1,000" / "12,000,000"

# Direction antonyms, RU+EN. Word-boundary stems so one pattern covers the
# Russian morphology (снижает/снижается/снизили/снижение -> \bсни[зж]\w*);
# с/ш and з/ж alternations are handled explicitly (повысил/повышает ->
# \bповы[сш]\w*). «расти» is matched by finite forms only: a bare \bраст\w*
# fires on «раствор/растение», and \bрост\w* on «Ростов» (negative lookahead
# keeps роста/росту but drops росто-/рости-/росте-). Bare «рос\w*» is avoided
# on purpose: it would fire on «российский». Negation («не увеличивает») is
# resolved per match in _polarity_markers, not here.
_POLARITY_DOWN = re.compile(
    r"\bсни[зж]\w*|\bпони[зж]\w*|\bуменьш\w*|\bпад\w*|\bупа[дл]\w*|\bупасть\b|\bсокра[тщ]\w*"
    r"|\bспад\w*|\b(?:по|у)?дешев\w*"
    r"|\bменьше\b|\bменее\b|\bниже\b|\bмедленнее\b"
    r"|\bdecreas\w*|\bdeclin\w*|\bfall\w*|\bfell\b|\bshrink\w*|\bshrank\b|\bless\b|\bfewer\b|\bslower\b",
    re.IGNORECASE,
)
_POLARITY_UP = re.compile(
    r"\bувелич\w*|\bповы[сш]\w*|\bвырас\w*|\bвырос\w*"
    r"|\bрост(?![оие])\w*"
    r"|\bраст(?:е|ё)т\b|\bрастут\b|\bрасти\b|\bрастущ\w*"
    r"|\bрос(?:ла|ло|ли)?\b"
    r"|\b(?:по)?дорож\w*|\bподня\w*|\bнара[стщ]\w*|\bприрост\w*"
    r"|\bбольше\b|\bболее\b|\bвыше\b|\bбыстрее\b"
    r"|\bincreas\w*|\brise\b|\brises\b|\brising\b|\brose\b|\brisen\b"
    r"|\bgrow\w*|\bgrew\b|\bmore\b|\bfaster\b",
    re.IGNORECASE,
)


def _numbers(t: str) -> tuple[Counter[float], Counter[float], Counter[float]]:
    """(percent, percent-points, absolute) multisets of comparable values.

    Three separate kinds: 20% != 20 п.п. != 20. Scale words are folded into
    the value ("1,5 млн" == "1500000"), comma-grouped thousands are one number
    ("1,000" == "1000"). Rounding strips float artifacts left by the multiplier.
    """
    perc: Counter[float] = Counter()
    points: Counter[float] = Counter()
    absol: Counter[float] = Counter()
    for m in _NUM_RE.finditer(t.lower()):
        s = m["num"]
        v = float(s.replace(",", "")) if _GROUPED_RE.fullmatch(s) else float(s.replace(",", "."))
        unit = m["unit"] or ""
        if unit.startswith(("процентн", "п.")):  # percentage points
            points[round(v, 4)] += 1
        elif unit.startswith(("%", "процент")):
            perc[round(v, 4)] += 1
        else:
            absol[round(v * _scale(unit.rstrip(".")), 4)] += 1
    return perc, points, absol


def _scale(unit: str) -> float:
    """Multiplier of a scale word; 1.0 when absent or unrecognized."""
    if unit.startswith(("миллиард", "млрд")):
        return 1e9
    if unit.startswith(("миллион", "млн")):
        return 1e6
    if unit.startswith("тыс") or unit == "thousand":
        return 1e3
    if unit == "million":
        return 1e6
    if unit == "billion":
        return 1e9
    return 1.0


def _guards_pass(claim: str, reviewed: str) -> bool:
    """Hard preconditions for pairing: same numbers, no direction conflict."""
    return (_numbers(claim) == _numbers(reviewed)
            and not _polarity_conflict(claim, reviewed))


# «не» / "not" / "n't" within two words before a direction stem flips the
# assertion: «не увеличивает» contradicts both «увеличивает» and «снижает».
_NEGATION = {"не", "not"}


def _negated_before(text: str, pos: int) -> bool:
    """True if a negation word sits within two words before *pos*."""
    window = re.findall(r"[\w'’]+", text[:pos])[-2:]
    return any(w.lower() in _NEGATION or w.lower().endswith(("n't", "n’t"))
               for w in window)


def _polarity_markers(t: str) -> tuple[set[str], set[str]]:
    """(plain, negated) direction-marker sets, each a subset of {'down', 'up'}."""
    plain: set[str] = set()
    negated: set[str] = set()
    for direction, rx in (("down", _POLARITY_DOWN), ("up", _POLARITY_UP)):
        for m in rx.finditer(t):
            (negated if _negated_before(t, m.start()) else plain).add(direction)
    return plain, negated


def _polarity_conflict(a: str, b: str) -> bool:
    """True if the two texts assert incompatible directions.

    Plain opposites conflict («снижает» vs «увеличивает»), and a negated
    direction conflicts with ANY plain direction of the other text:
    «не увеличивает» rejects both «увеличивает» and «снижает» (the reviewed
    text asserts a change, the claim denies one). Two negations («не
    увеличивает» vs «не снижает») may hold together and do not conflict.
    """
    plain_a, neg_a = _polarity_markers(a)
    plain_b, neg_b = _polarity_markers(b)
    if ("up" in plain_a and "down" in plain_b) or ("down" in plain_a and "up" in plain_b):
        return True
    return bool((neg_a and plain_b) or (neg_b and plain_a))
