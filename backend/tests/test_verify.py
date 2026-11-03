"""Evidence Verification (v0.10): SSRF guard, text extraction, quote checks
against the page original and against the plausibility abstract. Fully
offline: DNS is mocked, HTTP uses httpx.MockTransport, sockets are blocked
by conftest."""
import json
import socket

import httpx
import pytest

from videofactcheck import verdict as ve
from videofactcheck import verify as vf

# public IP literal: the guard passes it without DNS (for offline tests)
PUB = "https://93.184.216.34/a"
# a quote long enough to pass the MIN_QUOTE_CHARS gate in verdict
LONG_QUOTE = "Дословная цитата достаточной длины для сверки с оригиналом страницы"


def _transport(handler):
    return httpx.MockTransport(handler)


# -- SSRF guard ----------------------------------------------------------------

def test_ssrf_private_and_special_hosts_blocked():
    """LLM-provided URLs with private/reserved addresses, localhost, *.local,
    or a non-standard scheme and port are never fetched."""
    for url in (
        "http://192.168.1.1/admin", "http://10.0.0.5/x", "http://127.0.0.1/x",
        "http://172.16.0.9/x", "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://100.64.0.1/x",  # CGNAT
        "http://0.0.0.0/x", "http://224.0.0.1/x",  # multicast
        "http://[::1]/x", "http://[fe80::1]/x", "http://[fc00::5]/x",
        "http://localhost/x", "http://printer.local/x",
        "ftp://93.184.216.34/x", "gopher://93.184.216.34/x",
        "http://93.184.216.34:8080/x",  # standard ports only
    ):
        assert not vf._url_allowed(url), url


def test_ssrf_public_host_allowed(monkeypatch):
    """A public host (DNS mocked, no network) passes the guard."""
    monkeypatch.setattr(vf.socket, "getaddrinfo",
                        lambda h, p: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                       ("93.184.216.34", 443))])
    assert vf._url_allowed("https://example.com/a")
    assert vf._url_allowed("https://93.184.216.34:443/a")  # the standard port is fine


def test_ssrf_dns_rebinding_blocked(monkeypatch):
    """A host with both a public and a private A record (DNS rebinding into an intranet) is blocked."""
    monkeypatch.setattr(vf.socket, "getaddrinfo", lambda h, p: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.1", 443))])
    assert not vf._url_allowed("https://evil.example/x")


def test_ssrf_redirect_to_private_blocked():
    """A redirect to a private address is not fetched: every hop is re-checked."""
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "http://192.168.0.1/secret"})

    assert vf.verify_source(PUB, LONG_QUOTE, transport=_transport(handler)) == "unreachable"
    assert seen == ["93.184.216.34"]  # no request ever reached the private host


def test_verify_source_ssrf_literal_unreachable():
    """A direct request to a cloud metadata endpoint is blocked without any network."""
    assert vf.verify_source("http://169.254.169.254/meta", LONG_QUOTE) == "unreachable"


class _Stop(Exception):
    """Sentinel: the connect address is captured, no real socket needed."""


def test_dns_rebinding_pinned_to_validated_ip(monkeypatch):
    """TOCTOU oracle: the guard resolve and the connect resolve return
    different addresses (TTL-0 DNS), yet the connection still goes only to
    the validated IP; the hostname never reaches the socket."""
    resolutions = iter([
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],  # the "second" resolve
    ])
    monkeypatch.setattr(vf.socket, "getaddrinfo", lambda h, p: next(resolutions))
    connected = []

    def fake_create_connection(address, *a, **kw):
        connected.append(address)
        raise _Stop("no real socket in tests")

    monkeypatch.setattr(vf.socket, "create_connection", fake_create_connection)
    with pytest.raises(_Stop):
        vf._GuardedBackend().connect_tcp("evil.example", 443)
    assert connected == [("93.184.216.34", 443)]  # pinned to the validated IP only


def test_guarded_backend_blocks_mixed_resolution(monkeypatch):
    """A [public, private] resolution list is a rebinding attempt: no connect at all."""
    monkeypatch.setattr(vf.socket, "getaddrinfo", lambda h, p: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))])
    with pytest.raises(vf.BlockedURLError):
        vf._GuardedBackend().connect_tcp("evil.example", 443)


# -- fetch / extract_text / verify_source -------------------------------------

def test_verify_source_verified_despite_typography():
    """An honest quote is found after normalize: quote/dash/yo typography."""
    def handler(request):
        return httpx.Response(200, text=
                              "<html><body><p>Он заявил: «Ёлки-палки — это прошлое» "
                              "и ушёл.</p></body></html>")
    assert vf.verify_source(PUB, "“Ёлки–палки - это прошлое”",
                            transport=_transport(handler)) == "verified"


def test_verify_source_not_found_on_paraphrase():
    """A paraphrase is not the original: the page is about something else, the quote is not there."""
    def handler(request):
        return httpx.Response(200, text="<html><body><p>В 2019 году исследование "
                              "показало значительное снижение артериального давления "
                              "в группе приёма препарата.</p></body></html>")
    assert vf.verify_source(PUB, "Исследование 2021 года обнаружило резкий рост "
                            "давления у всех участников опыта",
                            transport=_transport(handler)) == "not_found"


def test_verify_source_unreachable_on_404_and_timeout():
    """Non-200 and timeout mean unreachable: not the source's fault."""
    def not_found(request):
        return httpx.Response(404)
    assert vf.verify_source(PUB, LONG_QUOTE, transport=_transport(not_found)) == "unreachable"

    def slow(request):
        raise httpx.ConnectTimeout("no route")
    assert vf.verify_source(PUB, LONG_QUOTE, transport=_transport(slow)) == "unreachable"


def test_drip_feed_body_hits_deadline(monkeypatch):
    """Drip-feed (a byte every 7s) stays under every per-op timeout, so the
    shared monotonic deadline cuts the fetch (clock mocked, no sleep)."""
    ticks = iter([0.0] + [100.0] * 1000)
    monkeypatch.setattr(vf, "_now", lambda: next(ticks))

    def handler(request):
        return httpx.Response(200, content=iter([b"x"] * 1000))

    with pytest.raises(vf.UnreachableError):
        vf.fetch(PUB, transport=_transport(handler))


RU_SENTENCE = "Ёлки-палки — это прошлое, сказал он и ушёл."


def test_cp1251_page_without_charset_verified():
    """cp1251 without a declared charset: the U+FFFD-ratio sniff points to
    cp1251, so an honest source is not killed as not_found by garbage."""
    body = f"<html><body><p>{RU_SENTENCE}</p></body></html>".encode("cp1251")

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=body)

    assert vf.verify_source(PUB, RU_SENTENCE,
                            transport=_transport(handler)) == "verified"


def test_meta_charset_sniffed_over_lying_header():
    """A <meta charset> beats a lying iso-8859-1 header: meta charset takes
    priority when decoding."""
    body = ('<html><head><meta charset="windows-1251"></head><body>'
            f"<p>{RU_SENTENCE}</p></body></html>").encode("cp1251")

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=iso-8859-1"},
            content=body)

    assert vf.verify_source(PUB, RU_SENTENCE,
                            transport=_transport(handler)) == "verified"


def test_extract_text_drops_invisible_tags():
    """script/style/noscript/template take no part in matching: visible text only."""
    html = ("<html><head><script>alert(1)</script><style>.x{color:red}</style></head>"
            "<body><noscript>включите js</noscript><template><div>шаблон</div></template>"
            "<p>Видимый   текст</p><div>второй блок</div></body></html>")
    assert vf.extract_text(html) == "Видимый текст второй блок"


# -- normalize / quote_in_text ------------------------------------------------

def test_normalize_quotes_dashes_yo():
    assert vf.normalize("«Ёл» – «Мёд» — C−2") == "'ел' - 'мед' - c-2"
    assert vf.normalize("сло\u00adво") == "слово"      # the soft hyphen is dropped
    assert vf.normalize("a   b\t\nc") == "a b c"        # whitespace collapses


def test_quote_in_text_exact_beats_fuzzy():
    """An exact post-normalize match wins regardless of quote length."""
    text = "Он заявил: «Ёлки-палки — это прошлое» и ушёл."
    assert vf.quote_in_text("“Ёлки–палки - это прошлое”", text)


def test_quote_in_text_fuzzy_window():
    """A dropped word (eaten by markup) is forgiven; a word swap or a
    translation is already a paraphrase, rejected by the order/token checks."""
    sentence = "the study found that sleep deprivation significantly degrades " \
               "cognitive performance over many nights of testing"
    text = "Background and methods. " + sentence + " Conclusions follow."
    assert vf.quote_in_text(
        "sleep deprivation degrades cognitive performance", text)  # a word was dropped
    long_page = "filler text block. " * 400 + text + " other filler. " * 400
    assert vf.quote_in_text(
        "sleep deprivation degrades cognitive performance", long_page)
    # a word swap is a paraphrase: the token "strongly" is not on the page
    assert not vf.quote_in_text(
        "sleep deprivation strongly degrades cognitive performance", text)
    assert not vf.quote_in_text(
        "нехватка сна сильно ухудшает мыслительные способности людей", text)


def test_tokens_in_order_filters_reorder():
    """Word-order unit check. A reassembled sequence is not a subsequence
    of the text; a dropped source word is an allowed skip."""
    qt = "the drug increases mortality sharply said the study".split()
    page = "the study said the drug increases mortality sharply".split()
    assert not vf._tokens_in_order(qt, page)  # same words, different order
    honest = "sleep deprivation degrades cognitive performance".split()
    page_honest = ("sleep deprivation significantly degrades cognitive "
                   "performance".split())
    assert vf._tokens_in_order(honest, page_honest)  # a source word is skipped
    assert vf._tokens_in_order("testi testing".split(), "testing testi".split()) is False


def test_word_reorder_rejected():
    """A quote reassembled from page words keeps char-ratio >= 0.82 but
    breaks token order, hence not_found."""
    page = ("<html><body><p>The study said the drug increases mortality "
            "sharply over many nights.</p></body></html>")

    def handler(request):
        return httpx.Response(200, text=page)

    assert vf.verify_source(
        PUB, "the drug increases mortality sharply said the study",
        transport=_transport(handler)) == "not_found"


def test_deep_quote_with_damaged_ends_found():
    """An honest quote deeper than 42k with damaged ends (first word missing,
    tail cut) is found via anchor halves; a len/4-step window cannot reach it."""
    orig = ("The study found that sleep deprivation significantly degrades "
            "cognitive performance during prolonged testing periods")
    deep = "filler text block. " * 2500 + orig + " trailing filler."
    assert len(deep.split(orig)[0]) > 42_000  # the preamble is genuinely deep
    damaged = ("study found that sleep deprivation significantly degrades "
               "cognitive performance during prolonged testi")
    assert vf.quote_in_text(damaged, deep)


# -- verdict integration ------------------------------------------------------

def _sonar_with_sources(sources):
    """llm mock following the test_verdict_trust pattern: both passes return the same JSON."""
    def fake_chat(messages, **kw):
        return json.dumps({"verdict": "правда", "why": "x", "sources": sources},
                          ensure_ascii=False)
    return fake_chat


def test_verdict_drops_not_found_source(monkeypatch):
    """not_found means a likely paraphrase or fabrication: the source is
    dropped from votes and confidence falls as with an empty source list
    (the README promise)."""
    monkeypatch.setattr(ve.llm, "chat", _sonar_with_sources(
        [{"title": "T", "url": "https://reuters.com/a", "quote": LONG_QUOTE}]))
    monkeypatch.setattr(ve.verify, "verify_source", lambda url, quote: "not_found")
    res = ve.check("утверждение", "ru")
    assert res["votes"] == [] and res["relevant"] == 0
    assert res["confidence"] == "низкая"  # empty-list formula: 0.6 - 0.15


def test_verdict_keeps_unreachable_source(monkeypatch):
    """unreachable is not the source's fault: it stays in votes with a flag."""
    monkeypatch.setattr(ve.llm, "chat", _sonar_with_sources(
        [{"title": "T", "url": "https://reuters.com/a", "quote": LONG_QUOTE}]))
    monkeypatch.setattr(ve.verify, "verify_source", lambda url, quote: "unreachable")
    res = ve.check("утверждение", "ru")
    assert len(res["votes"]) == 1
    assert res["votes"][0]["verify"] == "unreachable"
    assert res["votes"][0]["domain"] == "reuters.com"
    assert res["confidence"] == "средняя"  # the trust-1.0 source stayed


def test_verdict_verifies_only_top2_by_trust(monkeypatch):
    """Latency budget: only the top-2 by trust get fetched, the rest are skipped."""
    monkeypatch.setattr(ve.llm, "chat", _sonar_with_sources([
        {"title": "R", "url": "https://reuters.com/a", "quote": LONG_QUOTE},
        {"title": "B", "url": "https://bbc.com/b", "quote": LONG_QUOTE},
        {"title": "X", "url": "https://unknown-site.xyz/c", "quote": LONG_QUOTE},
    ]))
    called = []

    def fake_verify(url, quote):
        called.append(url)
        return "verified"

    monkeypatch.setattr(ve.verify, "verify_source", fake_verify)
    res = ve.check("утверждение", "ru")
    assert sorted(called) == ["https://bbc.com/b", "https://reuters.com/a"]
    by_domain = {v["domain"]: v["verify"] for v in res["votes"]}
    assert by_domain == {"reuters.com": "verified", "bbc.com": "verified",
                         "unknown-site.xyz": "skipped"}


def test_verdict_verify_disabled_no_fetch(monkeypatch):
    """VFC_QUOTE_VERIFY=0 disables the layer: no fetch, the source is marked skipped."""
    def boom(url, quote):
        raise AssertionError("verify_source не должен вызываться при выключенном слое")
    monkeypatch.setattr(ve.verify, "verify_source", boom)
    monkeypatch.setenv("VFC_QUOTE_VERIFY", "0")
    monkeypatch.setattr(ve.llm, "chat", _sonar_with_sources(
        [{"title": "T", "url": "https://reuters.com/a", "quote": LONG_QUOTE}]))
    res = ve.check("утверждение", "ru")
    assert res["votes"][0]["verify"] == "skipped"
    assert len(res["votes"]) == 1  # the source is neither dropped nor verified
    assert not vf.enabled()


def test_verdict_short_quote_skips_verify(monkeypatch):
    """Short quotes are not verified: fuzzy on tiny strings is noise, and
    exact matching of one-char strings is trivial (so the test_security_fixes
    case stays offline)."""
    def boom(url, quote):
        raise AssertionError("короткая цитата не должна уходить на сверку")
    monkeypatch.setattr(ve.verify, "verify_source", boom)
    monkeypatch.setattr(ve.llm, "chat", _sonar_with_sources(
        [{"title": "T", "url": "https://reuters.com/a", "quote": "q"}]))
    res = ve.check("утверждение", "ru")
    assert res["votes"][0]["verify"] == "skipped"


# -- plausibility: the quote must come from the abstract ---------------------

def _plaus(monkeypatch, reply, abstract):
    import videofactcheck.plausibility as pl
    article = {"title": "T", "abstract": abstract, "year": "2020", "url": "u",
               "kind": "primary"}
    monkeypatch.setattr(pl.llm, "chat", lambda messages, **kw: reply)
    monkeypatch.setattr(pl, "_en_query", lambda c, l: "q")
    monkeypatch.setattr(pl, "_pmc", lambda q: [article])
    monkeypatch.setattr(pl, "_openalex", lambda q: [])
    return pl


def test_plausibility_quote_not_from_abstract_is_silent(monkeypatch):
    """The corpus is under our control: a quote not from the abstract makes
    the whole NLI reply untrusted, so the layer stays silent (no quote, no vote)."""
    reply = json.dumps({"relation": "refutes", "relevance": "directly_on_topic",
                        "why": "Наука против.",
                        "quote": "made up quote that appears nowhere in the abstract",
                        "article": 0}, ensure_ascii=False)
    pl = _plaus(monkeypatch, reply,
                "Background: we studied sleep deprivation in 40 volunteers "
                "for ten consecutive days of monitoring.")
    assert pl.check("X", "ru") is None


def test_plausibility_quote_from_abstract_passes(monkeypatch):
    reply = json.dumps({"relation": "supports", "relevance": "directly_on_topic",
                        "why": "Наука подтверждает.",
                        "quote": "sleep deprivation significantly degrades "
                                 "cognitive performance",
                        "article": 0}, ensure_ascii=False)
    pl = _plaus(monkeypatch, reply,
                "In controlled trials sleep deprivation significantly degrades "
                "cognitive performance across all measured tasks.")
    out = pl.check("X", "ru")
    assert out and out["influential"] is True
