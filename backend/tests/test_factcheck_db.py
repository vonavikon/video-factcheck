"""Этап 2 (ClaimReview): матчинг, порог похожести, маппинг рейтингов, отказоустойчивость."""
import json

from videofactcheck import factcheck_db as fc


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
    def json(self):
        return self._p


def test_no_key_skips_layer(monkeypatch):
    monkeypatch.delenv("VFC_FACTCHECK_KEY", raising=False)
    called = []
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: called.append(1))
    assert fc.match("любое утверждение") is None
    assert called == []


def test_match_with_human_verdict(monkeypatch):
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    payload = {"claims": [{
        "text": "Climate change is a hoax invented by China",
        "claimReview": [{"textualRating": "False", "publisher": {"name": " PolitiFact "},
                          "url": "https://www.politifact.com/article/1", "title": "Fact check"}],
    }]}
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(200, payload))
    res = fc.match("Climate change is a hoax invented by China")
    assert res["verdict"] == "ложно"
    assert res["engine"] == "claimreview"
    assert res["confidence"] == "высокая"
    assert "PolitiFact" in res["why"]
    assert res["votes"][0]["domain"] == "politifact.com"


def test_low_similarity_rejected(monkeypatch):
    """Похожие слова есть, но утверждение о другом — слой не должен врать попаданием."""
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    payload = {"claims": [{
        "text": "China invented the paper and gunpowder centuries ago",
        "claimReview": [{"textualRating": "True", "publisher": {"name": "X"},
                          "url": "https://x.com/1", "title": ""}],
    }]}
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(200, payload))
    assert fc.match("Climate change is a hoax invented by China") is None


def test_ru_rating_mapping():
    assert fc._map_rating("Ложь")[0] == "ложно"
    assert fc._map_rating("Правда")[0] == "правда"
    assert fc._map_rating("Вводит в заблуждение")[0] == "странно"
    assert fc._map_rating("Сложно сказать")[0] == "странно"  # незнакомая шкала — осторожно


def test_api_error_returns_none(monkeypatch):
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(403, {"error": {}}))
    assert fc.match("x") is None
    def boom(*a, **k):
        raise fc.httpx.ConnectError("net")
    monkeypatch.setattr(fc.httpx, "get", boom)
    assert fc.match("x") is None


# --- Guards against false matches (numbers, polarity) ---------------------------

def _mock_review(monkeypatch, reviewed_text):
    """API answers with a single candidate carrying the given reviewed text."""
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    payload = {"claims": [{
        "text": reviewed_text,
        "claimReview": [{"textualRating": "False", "publisher": {"name": "X"},
                         "url": "https://x.com/1", "title": ""}],
    }]}
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(200, payload))


def test_polarity_inversion_rejected(monkeypatch):
    """Similarity is 0.75, but the directions are opposite: no human verdict
    (trust 0.9) may be pinned on the inverted claim."""
    _mock_review(monkeypatch, "Препарат увеличивает риск заболевания на 20%")
    assert fc.match("Препарат снижает риск заболевания на 20%") is None


def test_different_percent_rejected(monkeypatch):
    """«на 20%» vs «на 30%»: token similarity is 1.0 ("20"/"30" are short
    tokens and dropped), only the number guard sees the difference."""
    _mock_review(monkeypatch, "Доля импорта выросла на 30%")
    assert fc.match("Доля импорта выросла на 20%") is None


def test_percent_vs_absolute_points_rejected(monkeypatch):
    """20% and 20 points are different quantities: percent multiset {20} vs
    absolute multiset {20} — ambiguous enough to reject conservatively."""
    _mock_review(monkeypatch, "Безработица в регионе снизилась на 20 пунктов")
    assert fc.match("Безработица в регионе снизилась на 20%") is None


def test_same_numbers_and_direction_still_match(monkeypatch):
    """Same numbers and same direction: the layer behaves as before the guards."""
    _mock_review(monkeypatch, "Исследование показало, что препарат снижает риск заболевания на 20%")
    res = fc.match("Препарат снижает риск заболевания на 20%")
    assert res is not None
    assert res["engine"] == "claimreview"
    assert res["verdict"] == "ложно"
    assert res["similarity"] == 1.0


def test_direction_stems_catch_morphology(monkeypatch):
    """One stem must cover both aspects: снижается (impf) and снизили (pf)."""
    _mock_review(monkeypatch, "Риск снизили на 20% при вакцинации")
    res = fc.match("Риск снижается на 20% при вакцинации")
    assert res is not None  # same direction (down), only morphology differs
    _mock_review(monkeypatch, "Риск увеличили на 20% при вакцинации")
    assert fc.match("Риск снижается на 20% при вакцинации") is None  # up vs down


def test_numbers_only_in_one_text_rejected(monkeypatch):
    """A numeric claim must not inherit the verdict of a numberless review."""
    _mock_review(monkeypatch, "Завод выпустил много автомобилей")
    assert fc.match("Завод выпустил 4680 автомобилей") is None


def test_english_polarity_rejected(monkeypatch):
    _mock_review(monkeypatch, "Prices decreased by 20%")
    assert fc.match("Prices increased by 20%") is None


def test_scale_words_folded_into_value(monkeypatch):
    """«1,5 млн» and «1500000» are the same number after the multiplier."""
    _mock_review(monkeypatch, "Государство выделило 1500000 рублей")
    res = fc.match("Государство выделило 1,5 млн рублей")
    assert res is not None
    assert res["engine"] == "claimreview"


def test_guard_lets_valid_candidate_through(monkeypatch):
    """A guard-failing top-similarity candidate must not shadow a valid one:
    the loop filters candidates, it does not reject the whole response."""
    monkeypatch.setenv("VFC_FACTCHECK_KEY", "AIzaFake")
    payload = {"claims": [
        {"text": "Курение снижает риск болезни Альцгеймера на 30%",  # sim 1.0, wrong number
         "claimReview": [{"textualRating": "True", "publisher": {"name": "Y"},
                          "url": "https://y.com/1", "title": ""}]},
        {"text": "Исследование показало, что курение снижает риск болезни Альцгеймера на 20%",
         "claimReview": [{"textualRating": "False", "publisher": {"name": "X"},
                          "url": "https://x.com/1", "title": ""}]},
    ]}
    monkeypatch.setattr(fc.httpx, "get", lambda *a, **k: _Resp(200, payload))
    res = fc.match("Курение снижает риск болезни Альцгеймера на 20%")
    assert res is not None
    assert res["verdict"] == "ложно"  # verdict of the valid candidate, not the wrong-number one


# --- Review round 2: negation, missing antonym pairs, pp class, thousands ---

def test_negation_ru_rejected(monkeypatch):
    """«не увеличивает» vs «увеличивает»: sim 1.0, numbers equal — only the
    negation-aware polarity guard sees the contradiction. A negated direction
    also conflicts with the plain opposite («не увеличивает» vs «снижает»)."""
    _mock_review(monkeypatch, "Препарат увеличивает риск заболевания на 20%")
    assert fc.match("Препарат не увеличивает риск заболевания на 20%") is None
    _mock_review(monkeypatch, "Препарат снижает риск заболевания на 20%")
    assert fc.match("Препарат не увеличивает риск заболевания на 20%") is None


def test_negation_en_rejected(monkeypatch):
    """EN negation: "does not increase" / "doesn't increase" vs "increases" -> None."""
    _mock_review(monkeypatch, "The drug increases the risk of disease by 20%")
    assert fc.match("The drug does not increase the risk of disease by 20%") is None
    _mock_review(monkeypatch, "The drug increases the risk by 20%")
    assert fc.match("The drug doesn't increase the risk by 20%") is None


def test_price_antonyms_rejected(monkeypatch):
    """подорожал/подешевел and дороже/дешевле are frequent inversion pairs."""
    _mock_review(monkeypatch, "Бензин подешевел на 20%")
    assert fc.match("Бензин подорожал на 20%") is None
    _mock_review(monkeypatch, "Билеты стали дешевле на 20%")
    assert fc.match("Билеты стали дороже на 20%") is None


def test_up_vs_down_movement_rejected(monkeypatch):
    """«поднялись» was missing while «упали» was caught — asymmetric guard."""
    _mock_review(monkeypatch, "Цены упали на 20%")
    assert fc.match("Цены поднялись на 20%") is None


def test_narashil_vs_sokratil_rejected(monkeypatch):
    _mock_review(monkeypatch, "Компания сократила выручку на 20%")
    assert fc.match("Компания нарастила выручку на 20%") is None


def test_prirost_vs_spad_rejected(monkeypatch):
    """Prefixed nouns: bare \bрост/\bпад stems do not see прирост/спад."""
    _mock_review(monkeypatch, "Спад продаж составил 20%")
    assert fc.match("Прирост продаж составил 20%") is None


def test_percent_points_separate_class(monkeypatch):
    """20% and 20 процентных пунктов are different quantities; the abbreviation
    «п.п.» belongs to the same class as the full form."""
    _mock_review(monkeypatch, "Инфляция снизилась на 20%")
    assert fc.match("Инфляция снизилась на 20 процентных пунктов") is None
    _mock_review(monkeypatch, "Инфляция снизилась на 20 процентных пунктов")
    assert fc.match("Инфляция снизилась на 20 п.п.") is not None


def test_en_thousand_separator(monkeypatch):
    """"1,000" is one thousand, not the decimal 1.0 — must match "1000"."""
    _mock_review(monkeypatch, "The city has 1000 people")
    assert fc.match("The city has 1,000 people") is not None
    _mock_review(monkeypatch, "Ущерб составил 12000000 долларов")
    assert fc.match("Ущерб составил 12,000,000 долларов") is not None


def test_no_polarity_trigger_for_plant_and_city_words(monkeypatch):
    r"""Old \bраст\w* fired on раствор/растение, \bрост\w* on Ростов, rejecting
    compatible pairs as up/down conflicts."""
    _mock_review(monkeypatch, "Раствор глюкозы снизили до 20%")
    assert fc.match("Раствор содержит 20% глюкозы") is not None
    _mock_review(monkeypatch, "Количество школ снизили до 20 в Ростове")
    assert fc.match("В Ростове открылось 20 новых школ") is not None
    _mock_review(monkeypatch, "Настой снижает давление на 20%")
    assert fc.match("Экстракт растения снижает давление на 20%") is not None
