"""Stage 1 quality: significance filter, numeric claim fields, prompt
context, backward compatibility of extract without channel/published."""
import json

from videofactcheck import claims as cl


def _seg(i, text="текст"):
    return {"id": i, "t_start": float(i * 5), "t_end": float(i * 5 + 4), "text": text}


def _mock_llm(monkeypatch, payload, captured=None):
    """Replace llm.chat: return the payload, record messages into captured when given."""
    def fake_chat(messages, **kw):
        if captured is not None:
            captured.append(messages)
        return json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(cl.llm, "chat", fake_chat)


def test_significance_filter(monkeypatch):
    """significance 5 and 3 stay as claims, 1 goes to skipped as insignificant."""
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
    """For the numeric category, {subject, indicator, value_norm, unit, year}
    pass through to the output; other categories get no statistical fields."""
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
    """The later batch gets a context prefix, the tail of segment 12 (at most
    120 chars); channel/date land in the system prompt; the first batch gets none."""
    captured = []
    _mock_llm(monkeypatch, {"claims": [], "skipped": []}, captured)
    segs = [_seg(i) for i in range(1, 15)]  # 14 segments, 2 batches of 12
    segs[11]["text"] = "длинный " * 50  # segment 12: the previous one for the 2nd batch
    cl.extract(segs, title="Как устроен сон", channel="Наука проспект",
               published="2026-01-05")
    assert len(captured) == 2

    sys_msg = captured[0][0]["content"]
    assert "Канал: Наука проспект" in sys_msg
    assert "дата: 2026-01-05" in sys_msg
    assert "Как устроен сон" in sys_msg
    assert "рассказчик" in sys_msg  # unnamed speakers are forbidden

    # batches run in parallel, call order is not fixed, match by content
    first_batch = next(c for c in captured if not c[1]["content"].startswith("[контекст] "))
    later_batch = next(c for c in captured if c[1]["content"].startswith("[контекст] "))
    assert "[контекст]" not in first_batch[1]["content"]  # the first batch has nothing to build context from
    first_line = later_batch[1]["content"].split("\n")[0]
    assert len(first_line) <= len("[контекст] ") + cl.CONTEXT_TAIL_CHARS
    assert any(f"[{i}]" in later_batch[1]["content"] for i in range(12, 25))  # the batch segments are in place


def test_extract_without_channel_published(monkeypatch):
    """Backward compatibility: extract without channel/published and claims
    without significance still work; no claim is lost and no channel line
    goes into the prompt."""
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
