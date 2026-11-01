"""Дедупликация утверждений без внешних моделей (v1; embeddings e5 — потом).

Два уровня сравнения по нормализованным строкам:
1. Точный — нормализованный хэш (lower, без пунктуации, пробелы схлопнуты).
   Числа-слова в цифры не переводим: «семьдесят два» и «72» на этом уровне
   разные — для v1 это допустимо.
2. Парафраз — difflib.SequenceMatcher(None, a, b).ratio() по нормализованным
   строкам, ratio >= threshold → дубликат. O(n²) по парам: claims <= 150,
   строки короткие; пары с разницей длин > 60% в difflib не пускаем.

Числа: если в двух утверждениях есть числа (\\d+) и множества не равны —
это НЕ дубликат даже при высокой похожести («написал за 72 часа» и
«написал за 90 часов» — разные утверждения).

Порог 0.72 консервативный: точность важнее полноты, лучше отправить
лишний парафраз в проверку, чем склеить два разных утверждения.
"""
import hashlib
import re
from difflib import SequenceMatcher

DEFAULT_THRESHOLD = 0.72

# Отсев по длинам: max(ratio) = 2*min/(min+max); при разнице > 60% это
# даёт < 0.571, до порога >= 0.58 такая пара не дотянет никогда —
# difflib для неё можно не запускать.
_MAX_LEN_GAP = 0.6

_PUNCT_RE = re.compile(r"[^\wа-яё\s]")
_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\d+")


def normalize(text: str) -> str:
    """Lower, без пунктуации, пробелы схлопнуты (как claims.normalize)."""
    t = text.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def extract_numbers(text: str) -> set[str]:
    """Множество чисел (подстроки \\d+) нормализованного текста."""
    return set(_NUM_RE.findall(text))


def _skip_by_length(a: str, b: str) -> bool:
    """True, если разница длин > 60% — ratio такой пары гарантированно мала."""
    if not a or not b:
        return False  # пустые строки сравниваем напрямую (ratio 0.0 или 1.0)
    shorter, longer = min(len(a), len(b)), max(len(a), len(b))
    return (longer - shorter) / longer > _MAX_LEN_GAP


def _is_dup(a_norm: str, a_nums: set[str], b_norm: str, b_nums: set[str],
            threshold: float) -> bool:
    """Дубликат ли одна нормализованная строка другой при пороге threshold."""
    if a_norm == b_norm:
        return True
    if a_nums and b_nums and a_nums != b_nums:
        return False  # разные числа — разные утверждения, даже при похожем тексте
    if _skip_by_length(a_norm, b_norm):
        return False
    return SequenceMatcher(None, a_norm, b_norm).ratio() >= threshold


def dedup_claims(claims: list[dict], key: str = "claim",
                 threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Уникальные утверждения; порядок сохранён, первый встреченный выигрывает.

    claims — список dict, текст берётся из поля key. Возвращает ссылки на
    исходные dict (не копии). Точный повтор отбрасывается по хэшу, парафраз —
    по ratio >= threshold против уже оставленных. Отсев по длинам корректен
    при threshold >= 0.58; не передавайте порог ниже 0.6.
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
