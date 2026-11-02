"""Stage 1: extraction of checkable claims from transcript segments.

Decisions B10-B11: schema with a verbatim quote and a category, WITHOUT numeric
specificity; opinions/forecasts/unfalsifiable statements are collected separately
(as "skip"); dedup uses a normalized hash (embeddings if ever needed).

2026-10-29: the previous segment goes into the prompt as a [контекст] line (subject
for anaphora, not a quote source); channel/published go into the prompt context;
significance filtering happens in a single call (significance 1-5 plus a
deterministic filter, SIGNIFICANCE_MIN); when category="число", normalized fields
{subject, indicator, value_norm, unit, year}.
"""
import hashlib
import re

from . import llm
from .transcript import fmt_ts

SYSTEM = """Ты — ассистент факт-чека. Тебе дают пронумерованные сегменты транскрипта видео \
с таймкодами. Найди в речи ПРОВЕРЯЕМЫЕ УТВЕРЖДЕНИЯ о мире: факты, числа, даты, события, \
причинно-следственные связи, заявления о свойствах вещей/людей/методов.

НЕ проверяемы (записывай с type=skip): мнения и оценки («я считаю», «лучший»), \
прогнозы будущего, нефальсифицируемые утверждения, гипербола и шутки, \
слова ведущего-развлекателя, анонсы («дальше мы поговорим»), цитаты без атрибуции.

Правила:
- quote — ДОСЛОВНАЯ короткая цитата из сегмента (не выдумывай, копируй из текста)
- claim — утверждение одним предложением, нормализованное (сущность + предикат) \
и САМОДОСТАТОЧНОЕ: имена вместо местоимений («Маск основал», а не «он основал»), \
единицы явно («20 млн долларов», а не «столько-то»), время привязано \
(«в 2019 году», а не «в прошлом году»)
- seg — id сегмента, откуда взято (один сегмент)
- category: число | дата | медицина | наука | история | экономика | политика | техника | другое
- significance — важность проверки, целое 1–5: 5 = конкретное число/дата/имя, \
причинно-следственная связь, не общеизвестно; 3 = обычный проверяемый факт; \
1–2 = рамочные фразы («сегодня поговорим о...»), анонсы, тривиальности, общеизвестное
- checkability_reason — кратко (до 15 слов), почему утверждение проверяемо
- при category=«число» добавь поля: subject (о ком/о чём утверждение), \
indicator (что измеряется), value_norm (значение цифрами, числительные словами \
переведи: «три четверти» → 0.75, «половина» → 0.5, «два миллиона» → 2000000), \
unit (единица: «доля», «руб.», «чел.»), year (явно названный год, иначе null)
- до 10 утверждений на порцию; бери значимое, не мусор
- отвечай ТОЛЬКО JSON: {"claims":[{"quote":"...","claim":"...","seg":12,"type":"fact",\
"category":"...","significance":4,"checkability_reason":"...","subject":"...",\
"indicator":"...","value_norm":0.75,"unit":"доля","year":2019}], \
"skipped":[{"quote":"...","reason":"мнение"}]}

Перед сегментами может идти строка [контекст] — конец предыдущего сегмента речи. \
Она нужна ТОЛЬКО чтобы понять субъекта анфоры («он изучал» — кто именно «он»): \
цитаты и утверждения из [контекст] НЕ извлекай, они уже разобраны в своей порции.

Сегменты:
"""

MAX_CLAIMS_PER_VIDEO = 150  # soft storage cap; the whole video is extracted,
                            # the money budget lives in verdict selection (pipeline)
SIGNIFICANCE_MIN = 3        # selection threshold: lower scores go to skipped with reason "незначимо"
CONTEXT_TAIL_CHARS = 120    # tail cut of the previous segment for the [контекст] line


def normalize(text: str) -> str:
    t = text.lower()
    t = re.sub(r"[^\wа-яё\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def claim_hash(claim: str) -> str:
    return hashlib.md5(normalize(claim).encode()).hexdigest()


def extract(segments: list[dict], lang: str = "ru", title: str = "",
            concurrency: int = 4, progress=None, on_batch=None,
            channel: str | None = None, published: str | None = None) -> dict:
    """Segments → {claims, skipped, batch_errors}. Batches are independent, run
    them in parallel (ThreadPoolExecutor): a 43-min video = 29 batches, sequential
    would take 30-60 minutes, interleaved is several times faster. progress(done, total)
    drives the status.

    channel/published (optional, None-safe) join title in the system prompt
    context. Claims with significance < SIGNIFICANCE_MIN deterministically go to
    skipped with reason "незначимо" after parsing (no second LLM call)."""
    from concurrent.futures import ThreadPoolExecutor

    claims: list[dict] = []
    skipped: list[dict] = []
    errors: list[int] = []
    ctx_bits = []
    if title:
        ctx_bits.append(f"видео называется «{title}»")
    if channel and published:
        ctx_bits.append(f"Канал: {channel}, дата: {published}")
    elif channel:
        ctx_bits.append(f"Канал: {channel}")
    elif published:
        ctx_bits.append(f"дата: {published}")
    context = ""
    if ctx_bits:
        context = ("\nКонтекст: " + "; ".join(ctx_bits)
                   + ". Спикера зови по имени, если оно известно из названия, "
                   "канала или речи, а не «рассказчик».")
    batch = 12
    starts = range(0, len(segments), batch)
    parts = [segments[i : i + batch] for i in starts]
    prevs = [segments[i - 1] if i > 0 else None for i in starts]

    def run_part(part: list[dict], prev: dict | None) -> list[dict]:
        lines = ""
        if prev is not None:  # anaphora subject from the previous segment, NOT a quote source
            tail = " ".join(prev["text"].split())[-CONTEXT_TAIL_CHARS:]
            lines += f"[контекст] {tail}\n"
        lines += "\n".join(
            f"[{s['id']}] [{fmt_ts(s['t_start'])}] {s['text']}" for s in part
        )
        try:
            text = llm.chat(
                [{"role": "system", "content": SYSTEM + context},
                 {"role": "user", "content": lines}],
                json_mode=True,
            )
            data = llm.parse_json(text)
        except Exception:  # noqa: BLE001: a broken batch must not kill the whole run
            errors.append(1)
            return []
        seg_map = {s["id"]: s for s in part}
        out = []
        for c in data.get("claims", []):
            seg = seg_map.get(c.get("seg"))
            if not seg:
                continue
            try:
                sig = int(c.get("significance"))
            except (TypeError, ValueError):
                sig = None  # field missing or garbage; do not silently drop the claim
            if sig is not None and sig < SIGNIFICANCE_MIN:
                skipped.append({"quote": (c.get("quote") or "").strip(),
                                "reason": "незначимо"})
                continue
            item = {
                "quote": (c.get("quote") or "").strip(),
                "claim": (c.get("claim") or "").strip(),
                "t_start": seg["t_start"], "t_end": seg["t_end"],
                "seg": c.get("seg"),
                "type": c.get("type", "fact"),
                "category": c.get("category", "другое"),
                "hash": claim_hash(c.get("claim") or ""),
            }
            if sig is not None:
                item["significance"] = sig
            reason = str(c.get("checkability_reason") or "").strip()
            if reason:
                item["checkability_reason"] = reason
            if item["category"] == "число":
                for k in ("subject", "indicator", "unit"):
                    v = str(c.get(k) or "").strip()
                    if v:
                        item[k] = v
                for k in ("value_norm", "year"):
                    if c.get(k) is not None:
                        item[k] = c[k]
            out.append(item)
        for s in data.get("skipped", []):
            skipped.append({"quote": (s.get("quote") or "").strip(),
                            "reason": s.get("reason", "")})
        return out

    done = 0
    from . import tracing
    tid = tracing.current_trace_id()

    def run_part_with_trace(part, prev):
        if tid:
            tracing.set_current_trace_id(tid)  # trace_id in every worker (langfuse)
        return run_part(part, prev)

    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(run_part_with_trace, part, prev) for part, prev in zip(parts, prevs)]
        for fut in as_completed(futs):
            part_claims = fut.result()
            claims.extend(part_claims)
            done += 1
            if progress:
                progress(done, len(parts))
            # pipeline: a finished batch moves on (ClaimReview) before extraction ends;
            # runs in this same thread, no races over mutable state
            if on_batch and part_claims:
                try:
                    on_batch(part_claims)
                except Exception:  # noqa: BLE001: the pipeline must not kill extraction
                    pass

    # dedup: exact repeats by hash + paraphrases (difflib, numbers protected)
    from .dedup import dedup_claims
    seen: set[str] = set()
    uniq: list[dict] = []
    for c in claims:
        if c["hash"] in seen:
            continue
        seen.add(c["hash"])
        uniq.append(c)
    uniq = dedup_claims(uniq, key="claim")
    return {"claims": uniq[:MAX_CLAIMS_PER_VIDEO], "skipped": skipped,
            "batch_errors": len(errors)}
