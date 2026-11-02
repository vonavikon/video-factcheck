"""Claim deduplication without external models (v1; e5 embeddings later).

Two comparison levels over normalized strings:
1. Exact: normalized hash (lower, no punctuation, whitespace collapsed).
   Number words are not converted to digits: "семьдесят два" and "72" are
   different at this level; acceptable for v1.
2. Paraphrase: difflib.SequenceMatcher(None, a, b).ratio() over normalized
   strings, ratio >= threshold → duplicate. O(n²) over pairs: claims <= 150,
   strings are short; pairs with a length gap > 60% never reach difflib.

Numbers: if both claims contain numbers (\\d+) and the sets differ,
this is NOT a duplicate even at high similarity ("написал за 72 часа" and
"написал за 90 часов" are different claims).

The 0.72 threshold is conservative: precision matters more than recall; better
to send one extra paraphrase for checking than to merge two different claims.
"""
import hashlib
import re
from difflib import SequenceMatcher

DEFAULT_THRESHOLD = 0.72

# Length-based pre-filter: max(ratio) = 2*min/(min+max); with a gap > 60% this
# gives < 0.571, so such a pair can never reach a threshold >= 0.58 and
# difflib can be skipped for it.
_MAX_LEN_GAP = 0.6

_PUNCT_RE = re.compile(r"[^\wа-яё\s]")
_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\d+")


def normalize(text: str) -> str:
    """Lower, no punctuation, whitespace collapsed (same as claims.normalize)."""
    t = text.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def extract_numbers(text: str) -> set[str]:
    """Set of numbers (\\d+ substrings) in the normalized text."""
    return set(_NUM_RE.findall(text))


def _skip_by_length(a: str, b: str) -> bool:
    """True if the length gap > 60%; such a pair's ratio is guaranteed low."""
    if not a or not b:
        return False  # empty strings are compared directly (ratio 0.0 or 1.0)
    shorter, longer = min(len(a), len(b)), max(len(a), len(b))
    return (longer - shorter) / longer > _MAX_LEN_GAP


def _is_dup(a_norm: str, a_nums: set[str], b_norm: str, b_nums: set[str],
            threshold: float) -> bool:
    """Whether one normalized string is a duplicate of the other at the given threshold."""
    if a_norm == b_norm:
        return True
    if a_nums and b_nums and a_nums != b_nums:
        return False  # different numbers mean different claims, however similar the text
    if _skip_by_length(a_norm, b_norm):
        return False
    return SequenceMatcher(None, a_norm, b_norm).ratio() >= threshold


def dedup_claims(claims: list[dict], key: str = "claim",
                 threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Unique claims; order preserved, the first one encountered wins.

    claims is a list of dicts, text is taken from the key field. Returns
    references to the original dicts (not copies). Exact repeats are dropped
    by hash, paraphrases by ratio >= threshold against the already kept ones.
    The length pre-filter is correct for threshold >= 0.58; do not pass
    a threshold below 0.6.
    """
    kept: list[dict] = []
    kept_norms: list[tuple[str, set[str]]] = []
    seen_hashes: set[str] = set()

    for c in claims:
        norm = normalize(str(c.get(key, "")))
        h = hashlib.md5(norm.encode()).hexdigest()
        if h in seen_hashes:
            continue
        nums = extract_numbers(norm)
        if any(_is_dup(n, m, norm, nums, threshold) for n, m in kept_norms):
            continue
        seen_hashes.add(h)
        kept_norms.append((norm, nums))
        kept.append(c)
    return kept
