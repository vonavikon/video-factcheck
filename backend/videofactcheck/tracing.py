"""Langfuse tracing for the pipeline (SDK v5, observation API). Optional:
enabled by LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST.
Without keys everything becomes a no-op.

Layout: a vfc-run root (trace_id = run_id) → nested phase spans; LLM calls
are logged as generations with usage_details and cost_details (bothub returns cost).
Extraction runs in threads — workers carry the trace_id via a contextvar.
"""
import contextvars
import hashlib
import os
import threading
from contextlib import contextmanager


def lf_trace_id(run_id: str) -> str:
    """Langfuse v5 requires a 32-hex trace id; derive a stable one from run_id."""
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
        from . import config  # noqa: F401 — guarantees .env is loaded
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
        except Exception as e:  # noqa: BLE001 — tracing must not break the pipeline
            print(f"[tracing] langfuse недоступен: {e}")
            _client = None
        return _client


def enabled() -> bool:
    return client() is not None


@contextmanager
def root(run_id: str, metadata: dict | None = None):
    """The run's root span; trace_id = run_id, everything in the thread nests inside.

    Important: NEVER swallow exceptions inside a contextmanager — Python
    raises RuntimeError("generator didn't stop after throw()") on a second
    yield after throw. Just re-raise.
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
        raise  # the exception propagates up, the span closes automatically


@contextmanager
def span(name: str, metadata: dict | None = None):
    """A nested phase span; parentship via the OTel context."""
    lf = client()
    if not lf:
        yield None
        return
    try:
        with lf.start_as_current_observation(name=name, metadata=metadata or None) as sp:
            yield sp
    except Exception:
        raise  # the exception propagates, the span closes automatically


def current_trace_id() -> str | None:
    return _trace_id.get()


def set_current_trace_id(tid: str | None) -> None:
    """Set the trace_id in the current thread (for extraction workers)."""
    _trace_id.set(tid)


def log_generation(*, name: str, model: str, prompt_tail: list, output: str | None,
                   usage: dict | None = None, error: str | None = None):
    """An LLM call as a generation. Inside the run's thread it nests into the current span;
    in an extraction worker it attaches to the trace by trace_id (contextvar)."""
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
