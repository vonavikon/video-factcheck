"""Langfuse-трейсинг пайплайна (SDK v5, observation-API). Опционален:
включается ключами LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST.
Без ключей всё превращается в no-op.

Схема: корень vfc-run (trace_id = run_id) → вложенные спаны фаз; вызовы LLM
логируются как generation с usage_details и cost_details (bothub отдаёт cost).
Экстракция идёт в потоках — воркеры несут trace_id через contextvar.
"""
import contextvars
import hashlib
import os
import threading
from contextlib import contextmanager


def lf_trace_id(run_id: str) -> str:
    """Langfuse v5 требует trace-id из 32 hex; выводим стабильный из run_id."""
    return hashlib.md5(f"vfc-{run_id}".encode()).hexdigest()

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("vfc_trace_id", default=None)
_lock = threading.Lock()
_client = None
_client_ready = False


def client():
    global _client, _client_ready
    if _client_ready:
        return _client
    with _lock:
        if _client_ready:
            return _client
        _client_ready = True
        from . import config  # noqa: F401 — гарантирует загрузку .env
        pub = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
        sec = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
        if not pub or not sec:
            return None
        try:
            from langfuse import Langfuse
            _client = Langfuse(
                public_key=pub, secret_key=sec,
                host=os.environ.get("LANGFUSE_HOST", "http://localhost:3000"),
            )
        except Exception as e:  # noqa: BLE001 — трейсинг не должен ронять пайплайн
            print(f"[tracing] langfuse недоступен: {e}")
            _client = None
        return _client


def enabled() -> bool:
    return client() is not None


@contextmanager
def root(run_id: str, metadata: dict | None = None):
    """Корневой спан прогона; trace_id = run_id, вкладывается всё в потоке.

    Важно: НИКОГДА не глотать исключения внутри contextmanager'а — Python
    бросает RuntimeError("generator didn't stop after throw()") при повторном
    yield после throw. Просто прокидываем.
    """
    _trace_id.set(lf_trace_id(run_id))
    lf = client()
    if not lf:
        yield None
        return
    from langfuse.types import TraceContext
    obs = lf.start_as_current_observation(
        name="vfc-run", trace_context=TraceContext(trace_id=lf_trace_id(run_id)),
        metadata=metadata or None)
    try:
        with obs as rt:
            yield rt
    except Exception:
        raise  # исключение прокидывается наверх, span закрывается автоматически


@contextmanager
def span(name: str, metadata: dict | None = None):
    """Вложенный спан фазы; родительство через OTel-контекст."""
    lf = client()
    if not lf:
        yield None
        return
    try:
        with lf.start_as_current_observation(name=name, metadata=metadata or None) as sp:
            yield sp
    except Exception:
        raise  # исключение прокидывается, спан закрывается автоматически


def current_trace_id() -> str | None:
    return _trace_id.get()


def set_current_trace_id(tid: str | None) -> None:
    """Установить trace_id в текущем потоке (для воркеров экстракции)."""
    _trace_id.set(tid)


def log_generation(*, name: str, model: str, prompt_tail: list, output: str | None,
                   usage: dict | None = None, error: str | None = None):
    """Вызов LLM как generation. В потоке прогона вкладывается в текущий спан;
    в воркере экстракции привязывается к трейсу по trace_id (contextvar)."""
    lf = client()
    tid = _trace_id.get()
    if not lf or not tid:
        return
    try:
        from langfuse.types import TraceContext
        kw = {"name": name, "as_type": "generation", "model": model,
              "input": [{"role": m.get("role"), "content": str(m.get("content"))[:600]}
                        for m in (prompt_tail or [])],
              "trace_context": TraceContext(trace_id=tid)}
        if usage:
            kw["usage_details"] = {
                "input": usage.get("prompt_tokens"),
                "output": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            }
            if usage.get("cost") is not None:
                kw["cost_details"] = {"total": float(usage["cost"])}
        if error:
            kw["level"] = "ERROR"
            kw["status_message"] = error[:300]
        if output:
            kw["output"] = output[:1000]
        gen = lf.start_observation(**kw)
        gen.end()
    except Exception:  # noqa: BLE001
        pass


def flush() -> None:
    if client():
        try:
            client().flush()
        except Exception:
            pass
