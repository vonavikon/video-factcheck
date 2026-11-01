"""Этап 2.5: проверка правдоподобия против научных баз.

Косвенные свидетельства: прямых факт-чеков нишевых утверждений нет и не будет,
но утверждение упирается в устоявшееся научное знание (пример из дизайна:
«диплом за 72 часа» ↔ наука депривации сна). Источники — Europe PMC
(медицина/биология, полные абстракты, без ключа) и OpenAlex (вся наука,
ключ ×10 лимитов). Судейство — дешёвый deepseek NLI по топ-3 абстрактам
с обязательной дословной цитатой.

Эпистемическое правило: косвенное свидетельство НИКОГДА не даёт «ложно».
Relation "refutes" показывается как отдельный статус «научные данные:
противоречит» рядом с вердиктом sonar, не вместо него.

Слой бесплатный для пользователя (кредиты списывает только sonar) и
необязательный: любая ошибка → None, пайплайн не страдает.
"""
import json
import os

import httpx

from . import llm

PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX_API = "https://api.openalex.org/works"

ADJUDICATE_PROMPT = """Ты — научный рецензент. Дано утверждение из видео и абстракты \
научных статей. Определи отношение устоявшегося научного знания к утверждению.

Правила:
- relation: "refutes" | "supports" | "insufficient"
- "refutes" = научные данные делают утверждение маловероятным. Это КОСВЕННОЕ \
свидетельство: прямых факт-чеков утверждения может не быть, но оно противоречит \
устоявшемуся знанию. Терминологические неточности — не refutes.
- "supports" = научные данные подтверждают суть утверждения
- "insufficient" = абстракты не по теме утверждения или пусты
- relevance: насколько абстракт-цитата исследует ИМЕННО это утверждение:
  "directly_on_topic" = тот же объект/воздействие и тот же исход (препарат в той \
же форме, та же популяция, то же следствие); "adjacent" = смежная тема (другая \
форма препарата, другая популяция, другой исход, обзор про другое); \
"off" = мимо темы
- why: одно предложение на языке {LANG} для показа пользователю
- quote: ДОСЛОВНАЯ цитата из абстракта с номером {N}, подтверждающая вывод; \
без подходящей цитаты — relation обязателен "insufficient"
- article: номер абстракта (0-based), из которого цитата
- отвечай ТОЛЬКО JSON: \
{"relation":"...","relevance":"...","why":"...","quote":"...","article":0}"""


def enabled() -> bool:
    """Слой включён по умолчанию; VFC_PLAUSIBILITY=0 выключает (экономия/отладка)."""
    return os.environ.get("VFC_PLAUSIBILITY", "1").strip() != "0"


def _en_query(claim: str, lang: str) -> str:
    """Поисковый запрос на английском: наука публикуется по-английски.
    Для ru-утверждения — один дешёвый вызов: переформулировать в поисковый EN."""
    if lang == "en":
        return claim
    try:
        out = llm.chat(
            [{"role": "system", "content": "Переведи утверждение в короткий англоязычный "
                                           "поисковый запрос для научной базы (тема + объект, "
                                           "без лишних слов). Ответь только запросом."},
             {"role": "user", "content": claim}],
            max_tokens=3000, temperature=0.0)
        return (out or "").strip().strip('"')[:200] or claim
    except Exception:  # noqa: BLE001 — слой необязательный
        return claim


def _pmc(query: str) -> list[dict]:
    try:
        r = httpx.get(PMC_API, params={"query": query, "format": "json",
                                       "pageSize": 5, "resultType": "core"},
                      timeout=12.0)
        if r.status_code != 200:
            return []
        out = []
        for a in (r.json().get("resultList") or {}).get("result", []):
            ab = (a.get("abstractText") or "").strip()
            if len(ab) < 120:  # пустые/обрезанные абстракты бесполезны для NLI
                continue
            pmid = a.get("pmid") or a.get("doi") or ""
            url = (f"https://europepmc.org/article/{a.get('source', 'MED')}/{pmid}"
                   if pmid else "")
            # pubTypeList.pubType: ["Review", "review-article", "Meta-Analysis", ...]
            ptypes = [str(x).lower() for x in
                      ((a.get("pubTypeList") or {}).get("pubType") or [])]
            kind = ("meta" if any("meta-analy" in x for x in ptypes)
                    else "review" if any("review" in x for x in ptypes) else "primary")
            out.append({"title": (a.get("title") or "")[:160],
                        "abstract": ab[:1400], "year": a.get("pubYear") or "",
                        "url": url, "kind": kind})
        return out[:3]
    except Exception:  # noqa: BLE001
        return []


def _openalex(query: str) -> list[dict]:
    key = os.environ.get("VFC_OPENALEX_KEY", "").strip()
    params = {"search": query, "per-page": 5}
    if key:
        params["api_key"] = key
    try:
        r = httpx.get(OPENALEX_API, params=params, timeout=12.0)
        if r.status_code != 200:
            return []
        out = []
        for w in (r.json() or {}).get("results", []):
            inv = w.get("abstract_inverted_index")
            if not inv:
                continue
            # инвертированный индекс → текст: слово → список позиций
            words: dict[int, str] = {}
            for word, positions in inv.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words[i] for i in sorted(words))[:1400]
            if len(abstract) < 120:
                continue
            url = w.get("doi") or (w.get("id") or "").replace("https://api.",
                                                              "https://.")
            out.append({"title": (w.get("display_name") or w.get("title") or "")[:160],
                        "abstract": abstract, "year": str(w.get("publication_year") or ""),
                        "url": url,
                        "kind": "review" if w.get("type") == "review" else "primary"})
        return out[:3]
    except Exception:  # noqa: BLE001
        return []


def _cjk(text: str) -> bool:
    """CJK-утечка: deepseek изредка отвечает по-китайски вопреки языку в промпте
    (наблюдалось вживую: why приходил на китайском вопреки промпту)."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def check(claim: str, lang: str = "ru") -> dict | None:
    """Утверждение → вердикт научного правдоподобия или None (слой промолчал).

    Возвращает {relation, why, quote, source: {title, url, year}}.
    relation "refutes" — «маловероятно по научным данным» (никогда «ложно»).
    """
    if not claim.strip():
        return None
    try:
        query = _en_query(claim, lang)
        articles = _pmc(query) or _openalex(query)
        if not articles:
            return None
        corpus = "\n\n".join(
            f"АБСТРАКТ {i}: {a['title']} ({a['year']})\n{a['abstract']}"
            for i, a in enumerate(articles))
        prompt = (ADJUDICATE_PROMPT.replace("{LANG}", "русском" if lang == "ru" else "English")
                  .replace("{N}", "0-" + str(len(articles) - 1)))
        # why обязан быть на языке пользователя: китайский ответ переспрашиваем,
        # максимум 3 попытки; устойчивая утечка — слой молчит (None)
        data: dict = {}
        for attempt in range(3):
            raw = llm.chat(
                [{"role": "system", "content": prompt + ("\nОТВЕТ СТРОГО НА РУССКОМ ЯЗЫКЕ."
                                                        if attempt and lang != "en" else "")},
                 {"role": "user", "content": f"УТВЕРЖДЕНИЕ: {claim}\n\n{corpus}"}],
                json_mode=True, max_tokens=4000, temperature=0.0)
            data = llm.parse_json(raw)
            if not _cjk((data.get("why") or "")):
                break
        relation = data.get("relation")
        if relation not in ("refutes", "supports", "insufficient"):
            return None
        if _cjk((data.get("why") or "")):
            return None  # показать китайский текст пользователю хуже, чем промолчать
        # гварды шага 2: наука влияет на вердикт только при
        # дословной цитате (правило В18 выше), ПРЯМОЙ релевантности и свежести
        # (год ≥ 2015 либо обзор/мета-анализ). relation без цитаты уже отброшен;
        # осторожный дефолт: NLI не выдал relevance = считаем смежной
        relevance = data.get("relevance")
        if relevance not in ("directly_on_topic", "adjacent", "off"):
            relevance = "adjacent"
        idx = data.get("article")
        src = articles[idx] if isinstance(idx, int) and 0 <= idx < len(articles) else articles[0]
        quote = (data.get("quote") or "").strip()
        if relation != "insufficient" and not quote:
            return None  # без дословной цитаты вывод не засчитывается (правило В18)
        try:
            src_yr = int(str(src.get("year") or "0"))
        except ValueError:
            src_yr = 0
        influential = (relation in ("refutes", "supports")
                       and relevance == "directly_on_topic"
                       and (src_yr >= 2015 or src.get("kind") in ("review", "meta")))
        return {
            "relation": relation,
            "relevance": relevance,
            "influential": influential,
            "why": (data.get("why") or "").strip()[:300],
            "quote": quote[:400],
            "source": {"title": src["title"], "url": src["url"], "year": src["year"],
                       "kind": src.get("kind", "primary")},
        }
    except Exception:  # noqa: BLE001 — слой необязательный: любая ошибка = молчание
        return None
