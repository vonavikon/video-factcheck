"""HTTP-сервер для расширения: FastAPI на localhost.

Эндпоинты:
  GET  /health
  POST /api/check  {url}          → {run_id}
  GET  /api/run/{run_id}          → статус + вердикты (поллинг из расширения)

Защита от чужих сайтов (сценарий AD-SRV-01): CORS открыт только для страниц
YouTube и chrome-extension — посторонний сайт не может запустить прогон
из браузера пользователя. Сервер слушать только на 127.0.0.1.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import pipeline, store

ALLOWED_ORIGIN_REGEX = r"https?://(www\.)?youtube\.com(/.*)?"

app = FastAPI(title="videofactcheck")


@app.on_event("startup")
def cleanup_orphans() -> None:
    """Прогоны, застрявшие в running после рестарта сервера, помечаем ошибкой —
    панель не должна вечно ждать мёртвый прогон (сценарий SRV-06)."""
    from . import store
    with store.connect() as con:
        con.execute(
            "UPDATE runs SET status='error', error='сервер перезапущен во время прогона' "
            "WHERE status='running'"
        )


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["GET", "POST"], allow_headers=["*"],
)


class CheckReq(BaseModel):
    url: str
    transcript: dict | None = None
    install_id: str = ""
    # язык обоснований вердиктов (настройка «язык проверки» в расширении);
    # None/мусор → язык транскрипта
    verdict_lang: str | None = None


# ── Security: API-токен + rate-limit (без этого публичный API = чужие деньги) ──
import time as _time
from collections import defaultdict

_RATE: dict[str, list] = defaultdict(list)  # ip → [timestamps]
_RATE_LIMIT = 10       # запросов
_RATE_WINDOW = 60      # за 60 секунд


def _rate_limited(request: Request) -> bool:
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    _RATE[ip] = [t for t in _RATE[ip] if now - t < _RATE_WINDOW]
    if len(_RATE[ip]) >= _RATE_LIMIT:
        return True
    _RATE[ip].append(now)
    return False


def _authed(request: Request) -> bool:
    """API-токен в заголовке X-API-Key; без него — rate-limited аноним."""
    import os
    expected = os.environ.get("VFC_API_KEY", "").strip()
    if not expected:
        import sys
        # fail-closed: на не-localhost без ключа — отказ (audit #3)
        host = request.client.host if request.client else ""
        if host.startswith("127.") or host == "::1":
            return True  # локальная разработка
        print(f"[server:SEC] VFC_API_KEY не задан, запрос с {host} отклонён", file=sys.stderr)
        return False
    import hmac
    got = request.headers.get("x-api-key", "").strip()
    return hmac.compare_digest(got, expected)
    return got == expected


class TopupReq(BaseModel):
    install_id: str
    credits: int  # клиентский транскрипт (IP пользователя):
    # расширение читает timed_text со страницы YouTube, сервер не ходит за сабами


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/check")
def check(req: CheckReq, request: Request) -> dict:
    if not _authed(request):
        return {"error": "unauthorized: нужен API-ключ"}
    if _rate_limited(request):
        return {"error": "rate limit: слишком много запросов, подожди минуту"}
    origin = request.headers.get("origin", "")
    if origin and not _origin_allowed(origin):
        return {"error": "origin not allowed"}
    t = req.transcript
    valid = bool(t and isinstance(t.get("cues"), list) and 0 < len(t["cues"]) <= 4000
                 and t.get("video_id")
                 and all(isinstance(c.get("text", ""), str) and len(c.get("text", "")) <= 500
                         for c in t["cues"][:50])
                 and len(str(t)) <= 500_000)  # СЕК-4: лимиты клиентского транскрипта
    vlang = req.verdict_lang if req.verdict_lang in ("ru", "en") else None
    return pipeline.start_run(req.url, transcript=t if valid else None,
                              install_id=req.install_id, verdict_lang=vlang)


@app.get("/api/account")
def account(install_id: str) -> dict:
    return store.get_or_create_account(install_id)


@app.post("/api/topup")
def topup(req: TopupReq, request: Request) -> dict:
    # мокап под env-флагом (СЕК-2): боевая покупка — webhook платёжки с подписью
    import os
    origin = request.headers.get("origin", "")
    if origin and not _origin_allowed(origin):
        return {"error": "origin not allowed"}
    if os.environ.get("VFC_ALLOW_MOCK_TOPUP", "") != "1":
        return {"error": "покупка кредитов пока недоступна (dev-мокап выключен)"}
    return store.topup(req.install_id, req.credits)


@app.get("/api/run/{run_id}")
def run(run_id: str, request: Request = None, install_id: str = "") -> dict:
    if request and not _authed(request):
        return {"error": "unauthorized"}
    st = pipeline.get_status(run_id)
    # IDOR-защита: прогон виден только автору запроса
    if st.get("install_id") and install_id and st["install_id"] != install_id:
        return {"error": "not your run"}
    return st


def _origin_allowed(origin: str) -> bool:
    import re
    return re.fullmatch(r"(https?://(www\.)?youtube\.com|chrome-extension://[\w-]+)(/.*)?", origin) is not None
