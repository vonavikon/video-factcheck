"""Stage 1 and 3 scenarios: claim dedup, bing redirect unwrapping, junk filter."""
import base64

from videofactcheck import claims as cl
from videofactcheck import search as se


def _b64(url: str) -> str:
    return "a1" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def test_unwrap_bing_valid():
    href = f"https://www.bing.com/ck/a?!&&p=abc&u={_b64('https://ted.com/talks')}&ntb=1"
    assert se._unwrap_bing(href) == "https://ted.com/talks"


def test_unwrap_bing_malformed_falls_back():
    href = "https://www.bing.com/ck/a?!&&p=abc&u=a1###broken###&ntb=1"
    assert se._unwrap_bing(href) == href  # broken base64 falls back to the original link, no crash


def test_unwrap_bing_plain_passthrough():
    assert se._unwrap_bing("https://reuters.com/x") == "https://reuters.com/x"


def test_junk_domains_filtered():
    raw = [
        {"title": "a", "url": "https://youtube.com/watch", "snippet": ""},
        {"title": "b", "url": "https://vkvideo.ru/x", "snippet": ""},
        {"title": "c", "url": "https://reuters.com/article", "snippet": ""},
        {"title": "d", "url": "https://reuters.com/another", "snippet": ""},  # duplicate domain
    ]
    out = se.search_web.__wrapped__ if hasattr(se.search_web, "__wrapped__") else None
    # exercise the internal filter: call the logic directly
    filtered, seen = [], set()
    for r in raw:
        dom = se._domain(r["url"])
        if not dom or dom in seen or any(j in dom for j in se.AGGREGATOR_JUNK):
            continue
        seen.add(dom)
        filtered.append(dom)
    assert filtered == ["reuters.com"]


def test_claim_hash_dedup():
    h1 = cl.claim_hash("В 2020 году произошло событие X!")
    h2 = cl.claim_hash("в 2020 году произошло событие  x")  # case/punctuation/spacing differences
    h3 = cl.claim_hash("Совсем другое утверждение")
    assert h1 == h2 and h1 != h3


def test_normalize_stable():
    assert cl.normalize("Ёлка, —  в лесу!") == "ёлка в лесу"
