"""Evidence Verification: match LLM-provided quotes against the source page.

The public README promises «made-up quotes get filtered out», but until this
layer a sonar source was accepted on non-empty url+quote alone: the model
could paraphrase, truncate or misattribute words. Here the page is fetched
(SSRF-guarded — the URL comes from an LLM, never trust it) and the quote is
matched against its visible text: exact match after normalization, else a
fuzzy window anchored on surviving quote fragments. plausibility.py reuses
the same matching against local abstracts — no fetch there.

SSRF defence is two-fold (DNS rebinding fix): the URL pre-flight checks
scheme/port/localhost and resolves once, and the custom transport pins the
actual TCP connect to the validated IP — httpcore would otherwise resolve
the name AGAIN at connect time, letting TTL-0 DNS show the guard a public
address and the socket a private one. TLS keeps the original hostname
(SNI + certificate identity).

verify_source() -> "verified" | "not_found" | "unreachable"; network errors,
timeouts, non-200 and SSRF blocks are "unreachable" — not the source's fault.
"""
import difflib
import ipaddress
import os
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpcore
import httpx

USER_AGENT = "video-factcheck/0.10 (+https://github.com/vonavikon/video-factcheck)"
FETCH_TIMEOUT = 8.0          # per-operation httpx timeout
FETCH_DEADLINE_S = 10.0      # monotonic ceiling per fetch: per-op timeouts miss drip-feed
RESOLVE_TIMEOUT_S = 3.0      # getaddrinfo has no timeout of its own
MAX_REDIRECTS = 3            # every hop is re-checked by the SSRF guard
MAX_BODY_BYTES = 1_500_000   # enough for quote matching, caps memory/latency
MAX_TEXT_CHARS = 300_000
FUZZY_THRESHOLD = 0.82       # SequenceMatcher ratio below this = quote absent
FUZZY_TOKEN_THRESHOLD = 0.7  # token-level tolerance for a markup-damaged word
MAX_FUZZY_TOKENS = 2         # how many quote words may be damaged at the ends
MAX_WINDOWS = 1200           # cap coarse fallback comparisons
MAX_PROBES = 50              # cap anchor-half occurrences probed per half
MIN_QUOTE_CHARS = 30         # shorter quotes: fuzzy ratio is noise, exact match only
MAX_TOKEN_GAP = 4            # page words allowed between consecutive quote words

_now = time.monotonic  # seam for deadline tests; never patch the time module


class BlockedURLError(Exception):
    """URL rejected by the SSRF guard (private/reserved host, bad scheme/port)."""


class UnreachableError(Exception):
    """Page not deliverable: non-200, too many redirects, deadline, empty body."""


def enabled() -> bool:
    """On by default; VFC_QUOTE_VERIFY=0 skips the layer (VFC_PLAUSIBILITY pattern)."""
    return os.environ.get("VFC_QUOTE_VERIFY", "1").strip() != "0"


# ── SSRF guard: the URL is attacker-influenced (LLM output) ──────────────────

_V4_BLOCKED = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4", "240.0.0.0/4"))
_V6_BLOCKED = tuple(ipaddress.ip_network(n) for n in (
    "::1/128", "fc00::/7", "fe80::/10", "ff00::/8"))


def _ip_blocked(ip) -> bool:
    """Private/reserved/multicast ranges must never be fetched."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 — judge the embedded IPv4
    nets = _V4_BLOCKED if ip.version == 4 else _V6_BLOCKED
    if any(ip in net for net in nets):
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _literal_ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _getaddrinfo_timeout(host: str):
    """getaddrinfo resolves over the network with NO timeout of its own; a
    dead resolver would eat the whole verification budget. Bounded wait in a
    throwaway thread (threads cannot be killed — it finishes in background)."""
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(socket.getaddrinfo, host, None).result(
            timeout=RESOLVE_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def _resolve_public_ips(host: str) -> list:
    """Guarded resolution: empty when unresolvable or when ANY address is
    private/reserved — one poisoned A-record is a rebinding attempt."""
    try:
        infos = _getaddrinfo_timeout(host)
    except (OSError, TimeoutError):  # gaierror / resolver timeout
        return []
    ips, seen = [], set()
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips if ips and not any(_ip_blocked(ip) for ip in ips) else []


def _validated_ip(host: str) -> str | None:
    """First public address of a guarded resolution — the IP to pin to."""
    ips = _resolve_public_ips(host)
    return str(ips[0]) if ips else None


def _host_allowed(host: str) -> bool:
    if not host:
        return False
    h = host.strip().strip("[]").lower().rstrip(".")
    if h == "localhost" or h.endswith(".local"):
        return False
    literal = _literal_ip(h)
    if literal is not None:
        return not _ip_blocked(literal)
    return bool(_resolve_public_ips(h))


def _url_allowed(url: str) -> bool:
    """http/https on standard ports only (80/443); :8080-style is out."""
    try:
        p = urlparse(url)
        port = p.port
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if port is not None and port != (80 if p.scheme == "http" else 443):
        return False
    return _host_allowed(p.hostname or "")


class _GuardedBackend(httpcore.SyncBackend):
    """Connect-time half of the SSRF guard (DNS rebinding / TOCTOU).

    The pre-flight resolved the name once, but httpcore resolves AGAIN inside
    socket.create_connection — and that call iterates every address, so even
    [public-refused, loopback] would connect. Here we resolve through the
    guarded path and hand httpcore the validated IP literal; the pool still
    starts TLS with the ORIGINAL hostname, so SNI and the certificate check
    stay bound to the name the user sees."""

    def connect_tcp(self, host, port, timeout=None, local_address=None,
                    socket_options=None):
        literal = _literal_ip(host)
        if literal is not None:
            if _ip_blocked(literal):
                raise BlockedURLError(host)
        else:
            ip = _validated_ip(host)
            if ip is None:
                raise BlockedURLError(host)
            host = ip  # pin: the socket only ever sees the validated address
        return super().connect_tcp(host, port, timeout=timeout,
                                   local_address=local_address,
                                   socket_options=socket_options)


class GuardedHTTPTransport(httpx.HTTPTransport):
    """Default transport for fetch(): every TCP connect goes through
    _GuardedBackend. trust_env defaults to False — an env proxy would move
    the connect out of the guard's sight."""

    def __init__(self, **kw):
        kw.setdefault("trust_env", False)
        super().__init__(**kw)
        # the pool reads its backend when opening connections; none exist yet
        self._pool._network_backend = _GuardedBackend()


# ── fetch + text extraction ──────────────────────────────────────────────────

_META_CHARSET_RE = re.compile(rb'charset\s*=\s*["\']?\s*([a-zA-Z0-9_\-]+)',
                              re.IGNORECASE)


def _decode_body(body: bytes, declared: str | None) -> str:
    """Charset triage. <meta charset> goes first (legacy servers lie with
    latin-1 headers), then a strict utf-8 try, then the header charset, and
    a cp1251 fallback when utf-8 mostly produced U+FFFD — the ru-web default:
    an honest cp1251 source must not die as not_found over mojibake."""
    candidates: list[str] = []
    m = _META_CHARSET_RE.search(body[:2048])
    if m:
        candidates.append(m.group(1).decode("ascii", "replace"))
    if declared and declared.lower() not in ("utf-8", "utf8"):
        candidates.append(declared)
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in candidates:
        try:
            return body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    text = body.decode("utf-8", "replace")
    if text.count("\ufffd") * 100 > len(text):  # >1% broken bytes
        try:
            return body.decode("cp1251")
        except UnicodeDecodeError:
            pass
    return text


def fetch(url: str, transport: httpx.BaseTransport | None = None) -> str:
    """GET the page manually following ≤ MAX_REDIRECTS redirects; every hop
    re-checked by the SSRF guard, connects pinned to validated IPs. Body
    capped at ~1.5 MB via streaming, whole fetch under one monotonic deadline
    (drip-feed servers keep every per-op read under the timeout forever).
    Raises BlockedURLError/UnreachableError/httpx errors; the caller maps
    any of them to "unreachable"."""
    deadline = _now() + FETCH_DEADLINE_S
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT}, trust_env=False,
                      transport=(transport if transport is not None
                                 else GuardedHTTPTransport())) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            if _now() > deadline:
                raise UnreachableError("fetch deadline exceeded")
            if not _url_allowed(url):
                raise BlockedURLError(url)
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise UnreachableError(f"HTTP {r.status_code}")
                chunks: list[bytes] = []
                size = 0
                for chunk in r.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BODY_BYTES:
                        break  # enough text for quote matching
                    if _now() > deadline:
                        raise UnreachableError("fetch deadline exceeded")
                body = b"".join(chunks)
                if not body:
                    raise UnreachableError("empty body")
                return _decode_body(body, r.encoding)
    raise UnreachableError("too many redirects")


class _TextExtractor(HTMLParser):
    """Visible text only: script/style/noscript/template carry no quotable
    prose (and scripts would leak code into matching)."""
    _SKIP = frozenset(("script", "style", "noscript", "template"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if not self._depth:
            s = " ".join(data.split())
            if s:
                self.parts.append(s)


def extract_text(html: str) -> str:
    """HTML -> normalized-ish visible prose, blocks joined with spaces."""
    p = _TextExtractor()
    p.feed(html)
    p.close()
    return " ".join(p.parts)[:MAX_TEXT_CHARS]


# ── quote matching ───────────────────────────────────────────────────────────

_NORM_TABLE = str.maketrans({
    "«": "'", "»": "'", "“": "'", "”": "'", "‘": "'", "’": "'", "‛": "'",
    "‚": "'", "„": "'", '"': "'",
    "−": "-", "–": "-", "—": "-", "‑": "-", "‐": "-",
    "ё": "е", "Ё": "Е",
    "\u00ad": "",  # soft hyphen: word­break artefacts of web typography
})


def normalize(s: str) -> str:
    """Common form for quote and page: case, quote/dash glyphs, ё->е,
    whitespace. Without this, honest quotes die on typography."""
    return " ".join(s.lower().translate(_NORM_TABLE).split())


class _ReusableMatcher:
    """SequenceMatcher with the quote cached on the b-side: b2j is built once
    and set_seq1 per window keeps deep-page scanning from re-indexing."""

    def __init__(self, q: str):
        self._m = difflib.SequenceMatcher(None, q, q, autojunk=False)

    def window_ok(self, window: str, threshold: float) -> bool:
        m = self._m
        m.set_seq1(window)
        return m.quick_ratio() >= threshold and m.ratio() >= threshold


_TOKEN_PUNCT = "'\"-.,;:!?()[]{}…"


def _tok_key(word: str) -> str:
    return word.strip(_TOKEN_PUNCT)


def _tokens_in_order(q_tokens: list[str], w_tokens: list[str]) -> bool:
    """Word-reorder filter: a reshuffled quote keeps a high char ratio,
    so additionally require the quote's words to appear as an ordered
    subsequence of the window, tolerating a few skipped page words (markup
    noise) and up to MAX_FUZZY_TOKENS damaged words at the ends."""
    pos = 0
    fuzzy_used = 0
    for tok in q_tokens:
        key = _tok_key(tok)
        if not key:
            continue
        limit = min(len(w_tokens), pos + MAX_TOKEN_GAP + 1)
        found = -1
        for i in range(pos, limit):
            if _tok_key(w_tokens[i]) == key:
                found = i
                break
        if found < 0:  # exact miss → one markup-damaged word may still match
            for i in range(pos, limit):
                w = _tok_key(w_tokens[i])
                if (w and w != key
                        and difflib.SequenceMatcher(None, key, w).ratio()
                        >= FUZZY_TOKEN_THRESHOLD):
                    found = i
                    fuzzy_used += 1
                    break
            if found < 0 or fuzzy_used > MAX_FUZZY_TOKENS:
                return False
        pos = found + 1
    return True


def _anchor_match(q: str, t: str, hit) -> bool:
    """Probe windows around surviving anchor halves — the first/last 15 chars
    of the quote, each split in two, so 1-2 edits at the very ends still
    leave a clean half for str.find. find() covers the WHOLE text: deep
    quotes are located at any offset, not just the capped window's reach.
    Windows try several extensions: dropped/inserted page words shift the
    far edge of the quote by more than any fixed padding."""
    win = len(q)
    deltas = (0, 8, 16, 24, 32, 48)  # absorbed word drop/insert sizes
    probes = 0
    for part, off in ((q[:7], 0), (q[7:15], 7)):  # head halves
        if len(part) < 6:
            continue
        pos = t.find(part)
        while pos != -1 and probes < MAX_PROBES:
            probes += 1
            start = max(0, pos - off)
            for delta in deltas:
                if hit(t[start:start + win + delta]):
                    return True
            pos = t.find(part, pos + 1)
    for part, after in ((q[-15:-8], 8), (q[-8:], 0)):  # tail halves
        if len(part) < 6:
            continue
        pos = t.find(part)
        while pos != -1 and probes < MAX_PROBES:
            probes += 1
            end = pos + len(part) + after
            for delta in deltas:
                if end - win - delta >= 0 and hit(t[end - win - delta:end]):
                    return True
            pos = t.find(part, pos + 1)
    return False


def _window_match(q: str, t: str, hit) -> bool:
    """Coarse fallback when all anchor halves are damaged: sliding window of
    ~quote length, step a quarter of it, comparisons capped, early exit."""
    win, step = len(q), max(1, len(q) // 4)
    for n, start in enumerate(range(0, max(1, len(t) - win + 1), step)):
        if n >= MAX_WINDOWS:
            break
        if hit(t[start:start + win + 16]):
            return True
    return False


def quote_in_text(quote: str, text: str, threshold: float = FUZZY_THRESHOLD) -> bool:
    """Exact normalized containment first; else near-verbatim fuzzy match:
    SequenceMatcher ratio >= threshold around anchor positions with a capped
    sliding-window fallback, both gated by a word-order check."""
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return False
    if q in t:
        return True
    if len(q) < MIN_QUOTE_CHARS:
        return False  # fuzzy ratio on short strings is false-positive noise
    matcher = _ReusableMatcher(q)
    q_tokens = q.split()

    def hit(window: str) -> bool:
        return (matcher.window_ok(window, threshold)
                and _tokens_in_order(q_tokens, window.split()))

    return _anchor_match(q, t, hit) or _window_match(q, t, hit)


def verify_source(url: str, quote: str,
                  transport: httpx.BaseTransport | None = None) -> str:
    """"verified" | "not_found" | "unreachable" for one (url, quote) pair."""
    try:
        html = fetch(url, transport=transport)
    except Exception:  # noqa: BLE001 — any delivery failure = unreachable
        return "unreachable"
    try:
        return "verified" if quote_in_text(quote, extract_text(html)) else "not_found"
    except Exception:  # noqa: BLE001 — undecodable page: cannot judge, do not punish
        return "unreachable"
