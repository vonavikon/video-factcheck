"""Stage 3: web search per claim.

Backends: bing (no key, personal testing; works from a local RU IP directly)
and serper (production, with VFC_SERPER_KEY: better quality, Google results).
DDG was dropped: blocked both locally and from datacenter IPs.
Snippets only; pages are a later iteration.
"""
import base64
import html as html_mod
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx

from . import config

AGGREGATOR_JUNK = (
    "pinterest.", "facebook.com", "vk.com", "ok.ru", "tiktok.com",
    "answers.yahoo", "quora.com", "dzen.ru", "livejournal.", "forum",
    "youtube.com", "vkvideo.ru", "rutube.ru",
)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
LINK_RE = re.compile(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', re.S)
SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _proxy() -> str | None:
    return os.environ.get("VFC_SEARCH_PROXY", "") or None


def _unwrap_bing(href: str) -> str:
    """bing.com/ck/a?!&&p=...&u=a1<base64url of the real URL> -> URL.

    A broken/forged base64 returns the original link, not a garbage URL.
    """
    try:
        q = parse_qs(urlparse(href).query)
        u = (q.get("u") or [""])[0]
        if u.startswith("a1"):
            pad = u[2:] + "=" * (-len(u[2:]) % 4)
            decoded = base64.urlsafe_b64decode(pad).decode("utf-8", errors="strict")
            if decoded.startswith(("http://", "https://")):
                return decoded
    except Exception:
        pass
    return href


def _make_queries(claim: str, lang: str) -> list[str]:
    """The LLM compresses the claim into search queries: claim language + English."""
    from . import llm
    try:
        text = llm.chat(
            [{"role": "system", "content":
              "Сожми утверждение в 2 поисковых запроса для веб-поиска: первый на языке "
              f"утверждения ({lang}), второй на английском. Каждый 3–7 слов, только ключевые "
              "слова (имена, числа, сущности), без вопросительных предложений. "
              'Ответ ТОЛЬКО JSON: {"queries":["...","..."]}'},
             {"role": "user", "content": claim}],
            json_mode=True, max_tokens=1000,
        )
        qs = [q.strip() for q in llm.parse_json(text).get("queries", []) if q and q.strip()]
        return qs[:2] or [claim[:100]]
    except Exception:  # noqa: BLE001 - degrade to the raw claim
        return [claim[:100]]


def _bing(claim: str, lang: str, n: int) -> list[dict]:
    mkt = "ru-RU" if lang == "ru" else "en-US"
    last_err: Exception | None = None
    for host in ("https://www.bing.com/search", "https://www.bing.com/search"):
        try:
            resp = httpx.get(
                host, params={"q": claim[:200], "mkt": mkt, "count": n + 6},
                headers=UA, timeout=25.0, follow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            results = []
            for b in resp.text.split('<li class="b_algo"')[1:]:
                m = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
                if not m:
                    continue
                url = _unwrap_bing(html_mod.unescape(m.group(1)))
                if not url.startswith("http"):
                    continue
                sn = re.search(r'<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', b, re.S) \
                    or re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
                results.append({
                    "title": html_mod.unescape(TAG_RE.sub("", m.group(2))).strip(),
                    "url": url,
                    "snippet": html_mod.unescape(TAG_RE.sub("", sn.group(1))).strip() if sn else "",
                })
            if results:
                return results
        except Exception as e:  # noqa: BLE001
            last_err = e
    if last_err:
        print(f"[search] bing недоступен: {last_err}")
    return []


def search_web(claim: str, lang: str = "ru", n: int = 6) -> list[dict]:
    """Claim -> results [{title,url,snippet,domain}] after junk filtering.

    Bing cannot be fed a whole sentence: the LLM compresses the claim into 2
    keyword queries (claim language + English); results are merged.
    """
    queries = _make_queries(claim, lang)
    raw: list[dict] = []
    for q in queries:
        if config.SEARCH_BACKEND == "serper" and config.SERPER_KEY:
            raw.extend(_serper(q, n))
        else:
            raw.extend(_bing(q, lang, n))
    out, seen = [], set()
    for r in raw:
        dom = _domain(r.get("url", ""))
        if not dom or dom in seen or any(j in dom for j in AGGREGATOR_JUNK):
            continue
        seen.add(dom)
        out.append({
            "title": r.get("title", "")[:200],
            "url": r["url"],
            "snippet": r.get("snippet", "")[:400],
            "domain": dom,
        })
        if len(out) >= n:
            break
    return out


def _serper(claim: str, n: int) -> list[dict]:
    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": config.SERPER_KEY, "Content-Type": "application/json"},
        json={"q": claim[:200], "num": n + 4},
        timeout=30.0,
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""),
         "snippet": r.get("snippet", "")}
        for r in resp.json().get("organic", [])
    ]
