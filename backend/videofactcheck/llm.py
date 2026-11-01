"""Тонкая абстракция LLM-провайдера (решение В9): OpenAI-совместимый чат.

Работает с bothub (deepseek-v4-flash) и любым OpenAI-совместимым эндпоинтом
(OpenRouter, Selectel) сменой VFC_LLM_BASE_URL/KEY/MODEL без правки кода.
"""
import json
import re
import time

import httpx

from . import config


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 8000,
    temperature: float = 0.2,
    retries: int = 2,
) -> str:
    """Один вызов chat/completions. Возвращает content (str).

    model=None → VFC_LLM_MODEL. deepseek-v4-flash — reasoning-модель: при малом
    max_tokens возвращает content=null (урок из video-digest-бота), поэтому
    дефолт 8000 и ретраи с удвоением при пустом content.
    """
    body: dict = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_err = ""
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                f"{config.LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.LLM_KEY}"},
                json=body,
                timeout=180.0,
            )
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                from . import tracing
                tracing.log_generation(name="llm", model=body["model"], prompt_tail=messages,
                                       output=None, error=last_err)
                time.sleep(2 * (attempt + 1))
                continue
            try:
                data = resp.json()
            except Exception as e:  # битый JSON-ответ — тоже ретрай (ревью P1-3)
                last_err = f"битый JSON ответа: {e}"
                from . import tracing
                tracing.log_generation(name="llm", model=body["model"], prompt_tail=messages,
                                       output=None, error=last_err)
                time.sleep(2 * (attempt + 1))
                continue
        except httpx.TransportError as e:  # ConnectError/ReadTimeout — ретрай, не потеря батча (ревью P1-3)
            last_err = f"транспорт: {type(e).__name__}: {e}"
            from . import tracing
            tracing.log_generation(name="llm", model=body["model"], prompt_tail=messages,
                                   output=None, error=last_err)
            time.sleep(2 * (attempt + 1))
            continue
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        if content and content.strip():
            from . import tracing
            tracing.log_generation(name="llm", model=body["model"], prompt_tail=messages,
                                   output=content, usage=data.get("usage") or {})
            return content
        # content=null при исчерпании max_tokens reasoning-моделью
        last_err = f"пустой content (finish={choice.get('finish_reason')}), usage={data.get('usage')}"
        body["max_tokens"] = min(body["max_tokens"] * 2, 16000)
        time.sleep(2)
    from . import tracing
    tracing.log_generation(name="llm", model=body["model"], prompt_tail=messages,
                           output=None, error=last_err)
    raise RuntimeError(f"LLM вызов не удался: {last_err}")


def parse_json(text: str) -> dict:
    """JSON из ответа модели: срежет ```-заборы и найдёт первый объект."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
