"""Качество этапа 1 (2026-10-29): significance-фильтр, числовая нормализация,
контекст в промпте, обратная совместимость extract без channel/published."""
import json

from videofactcheck import claims as cl


def _seg(i, text="текст"):
    return {"id": i, "t_start": float(i * 5), "t_end": float(i * 5 + 4), "text": text}


def _mock_llm(monkeypatch, payload, captured=None):
    """Подмена llm.chat: возвращает payload, пишёт messages в captured (если дан)."""
    def fake_chat(messages, **kw):
        if captured is not None:
            captured.append(messages)
        return json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(cl.llm, "chat", fake_chat)


def test_significance_filter(monkeypatch):
    """significance 5 и 3 остаются claims, 1 уходит в skipped с reason «незначимо»."""
    payload = {"claims": [
        {"quote": "q1", "claim": "Маск основал SpaceX в 2002 году", "seg": 1,
         "type": "fact", "category": "история", "significance": 5,
         "checkability_reason": "имя, дата, не общеизвестно"},
        {"quote": "q2", "claim": "Обычный проверяемый факт", "seg": 1,
         "type": "fact", "category": "наука", "significance": 3,
         "checkability_reason": "конкретное свойство"},
        {"quote": "q3", "claim": "Дальше мы поговорим о космосе", "seg": 2,
         "type": "fact", "category": "другое", "significance": 1,
         "checkability_reason": "рамочная фраза"},
    ], "skipped": []}
    _mock_llm(monkeypatch, payload)
    res = cl.extract([_seg(1), _seg(2)])
    assert len(res["claims"]) == 2
    assert res["skipped"] == [{"quote": "q3", "reason": "незначимо"}]
    kept = {c["claim"] for c in res["claims"]}
    assert "Маск основал SpaceX в 2002 году" in kept
    assert "Дальше мы поговорим о космосе" not in kept
    assert res["batch_errors"] == 0


def test_numeric_claim_fields_pass(monkeypatch):
    """category=«число»: {subject, indicator, value_norm, unit, year} проходят
    в выход; прочим категориям статистические поля не навешиваются."""
    payload = {"claims": [
        {"quote": "три четверти взрослых", "claim": "Три четверти взрослых имеют смартфон",
         "seg": 1, "type": "fact", "category": "число", "significance": 5,
         "checkability_reason": "статистика с базой",
         "subject": "взрослые", "indicator": "доля владеющих смартфоном",
         "value_norm": 0.75, "unit": "доля", "year": 2025},
        {"quote": "q2", "claim": "Рим основан в 753 году до н. э.", "seg": 1,
         "type": "fact", "category": "история", "significance": 4,
         "checkability_reason": "дата"},
    ], "skipped": []}
    _mock_llm(monkeypatch, payload)
    res = cl.extract([_seg(1)])
    by_cat = {c["category"]: c for c in res["claims"]}
    num = by_cat["число"]
    assert num["value_norm"] == 0.75
    assert num["subject"] == "взрослые"
    assert num["indicator"] == "доля владеющих смартфоном"
    assert num["unit"] == "доля"
    assert num["year"] == 2025
    hist = by_cat["история"]
    assert "value_norm" not in hist and "subject" not in hist


def test_context_and_channel_in_prompt(monkeypatch):
    """Второй батч получает [контекст] — хвост 12-го сегмента (не длиннее 120
    символов); канал/дата — в системном промпте; в первом батче контекста нет."""
    captured = []
    _mock_llm(monkeypatch, {"claims": [], "skipped": []}, captured)
    segs = [_seg(i) for i in range(1, 15)]  # 14 сегментов → 2 батча по 12
    segs[11]["text"] = "длинный " * 50  # 12-й сегмент: предыдущий для 2-го батча
    cl.extract(segs, title="Как устроен сон", channel="Наука проспект",
               published="2026-01-05")
    assert len(captured) == 2

    sys_msg = captured[0][0]["content"]
    assert "Канал: Наука проспект" in sys_msg
    assert "дата: 2026-01-05" in sys_msg
    assert "Как устроен сон" in sys_msg
    assert "рассказчик" in sys_msg  # запрет безымянного спикера

    # батчи параллельны — порядок вызовов не фиксирован, ищем по содержимому
    first_batch = next(c for c in captured if not c[1]["content"].startswith("[контекст] "))
    later_batch = next(c for c in captured if c[1]["content"].startswith("[контекст] "))
    assert "[контекст]" not in first_batch[1]["content"]  # первому батчу не с чего
    first_line = later_batch[1]["content"].split("\n")[0]
    assert len(first_line) <= len("[контекст] ") + cl.CONTEXT_TAIL_CHARS
    assert any(f"[{i}]" in later_batch[1]["content"] for i in range(12, 25))  # сегменты батча на месте


def test_extract_without_channel_published(monkeypatch):
    """Обратная совместимость: extract без channel/published и claims без
    significance работают — утверждение не теряется, «Канал:» в промпт не идёт."""
    captured = []
    payload = {"claims": [
        {"quote": "q", "claim": "Старая схема без новых полей", "seg": 1,
         "type": "fact", "category": "наука"},
    ], "skipped": []}
    _mock_llm(monkeypatch, payload, captured)
    res = cl.extract([_seg(1)], title="T")
    assert len(res["claims"]) == 1
    assert res["claims"][0]["hash"] == cl.claim_hash("Старая схема без новых полей")
    assert res["skipped"] == [] and res["batch_errors"] == 0
    assert "Канал:" not in captured[0][0]["content"]
