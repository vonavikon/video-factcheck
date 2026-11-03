"""Paraphrase dedup: exact level, difflib level, number guard, ordering."""
from difflib import SequenceMatcher

from videofactcheck import dedup as dd


def _ratio(a: str, b: str) -> float:
    """Actual ratio over normalized strings, pinned by the tests."""
    return SequenceMatcher(None, dd.normalize(a), dd.normalize(b)).ratio()


def test_exact_duplicate_removed():
    claims = [
        {"id": 1, "claim": "В 2020 году произошло событие X!"},
        {"id": 2, "claim": "в 2020 году произошло событие  x"},  # case/punctuation/spacing differences
        {"id": 3, "claim": "Совсем другое утверждение"},
    ]
    out = dd.dedup_claims(claims)
    assert [c["id"] for c in out] == [1, 3]


def test_exact_duplicate_first_wins():
    claims = [
        {"id": 1, "claim": "Первый экземпляр"},
        {"id": 2, "claim": "первый  экземпляр."},
    ]
    out = dd.dedup_claims(claims)
    assert len(out) == 1
    assert out[0] is claims[0]  # the first occurrence wins, not a copy


def test_paraphrase_removed_default_threshold():
    # actual ratio 0.8861 >= 0.72, caught by the default threshold
    a = "На Земле было пять массовых вымираний"
    b = "На Земле произошло пять массовых вымираний"
    assert _ratio(a, b) >= 0.72
    out = dd.dedup_claims([{"id": 1, "claim": a}, {"id": 2, "claim": b}])
    assert [c["id"] for c in out] == [1]


def test_paraphrase_reorder_removed_at_floor_threshold():
    # a pure reorder of the same words; actual ratio 0.6216 < 0.72, so the
    # threshold in this test is the 0.6 floor. The alternative pair from the
    # spec scores 0.5823 < 0.6, below the floor, so the reorder is used here.
    a = "На Земле было пять массовых вымираний"
    b = "Пять массовых вымираний было на Земле"
    ratio = _ratio(a, b)
    assert 0.6 <= ratio < 0.72  # 0.6216
    out = dd.dedup_claims([{"id": 1, "claim": a}, {"id": 2, "claim": b}],
                          threshold=0.6)
    assert [c["id"] for c in out] == [1]


def test_different_numbers_both_kept():
    # actual ratio 0.8852 >= 0.72, but numbers {72} != {90}, so not a duplicate
    a = "Автор написал книгу за 72 часа"
    b = "Автор написал книгу за 90 часов"
    assert _ratio(a, b) >= 0.72
    out = dd.dedup_claims([{"id": 1, "claim": a}, {"id": 2, "claim": b}])
    assert [c["id"] for c in out] == [1, 2]


def test_same_numbers_paraphrase_removed():
    # same numbers ({72} == {72}), the guard does not block; ratio 0.8, a duplicate
    a = "Автор написал книгу за 72 часа"
    b = "Книгу автор написал за 72 часа"
    assert _ratio(a, b) >= 0.72
    out = dd.dedup_claims([{"id": 1, "claim": a}, {"id": 2, "claim": b}])
    assert [c["id"] for c in out] == [1]


def test_dissimilar_both_kept():
    # actual ratio 0.2319, far below the threshold
    a = "Кошки спят по 16 часов в сутки"
    b = "Рим был основан в 753 году до нашей эры"
    assert _ratio(a, b) < 0.72
    out = dd.dedup_claims([{"id": 1, "claim": a}, {"id": 2, "claim": b}])
    assert [c["id"] for c in out] == [1, 2]


def test_empty_input():
    assert dd.dedup_claims([]) == []


def test_order_preserved():
    claims = [
        {"id": 1, "claim": "Рим был основан в 753 году до нашей эры"},
        {"id": 2, "claim": "На Земле было пять массовых вымираний"},
        {"id": 3, "claim": "рим был основан в 753 году до нашей эры"},  # exact duplicate
        {"id": 4, "claim": "Кошки спят по 16 часов в сутки"},
        {"id": 5, "claim": "На Земле было пять массовых вымираний."},   # exact duplicate
    ]
    out = dd.dedup_claims(claims)
    assert [c["id"] for c in out] == [1, 2, 4]
    assert out[2] is claims[3]


def test_length_prefilter_no_false_merge():
    # normalized length gap 74% > 60%, difflib never runs, both claims
    # stay (the real ratio 0.407 is below the threshold anyway)
    a = "Численность волков в России растёт"
    b = ("Численность волков в России растёт уже несколько лет подряд "
         "по данным учёных из института проблем экологии и эволюции")
    na, nb = dd.normalize(a), dd.normalize(b)
    gap = (max(len(na), len(nb)) - min(len(na), len(nb))) / max(len(na), len(nb))
    assert gap > 0.6
    out = dd.dedup_claims([{"id": 1, "claim": a}, {"id": 2, "claim": b}])
    assert [c["id"] for c in out] == [1, 2]


def test_custom_key():
    claims = [
        {"id": 1, "text": "Утверждение одно"},
        {"id": 2, "text": "утверждение одно"},
    ]
    out = dd.dedup_claims(claims, key="text")
    assert [c["id"] for c in out] == [1]
