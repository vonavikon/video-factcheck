"""Registry of verification sources with weights (the system's shared dataset).

Research and live validation: 2026-10-29, two subagents (landscape survey + API probing).
Weight math: a piece of evidence enters the bayesian
accumulator as Δlogit = k_tier * τ_source * stance; τ for papers depends on citations.

Tiers (k_tier): direct human fact-checks 1.0; statistics for an exact figure 0.9;
direct confirmation by a reliable source via web 0.8; a scientific paper
(indirect) 0.7; encyclopedic 0.6; unvetted news 0.4.
Validation statuses: ok (live request 2026-10-29), key (works / need to request
a key), paid (paid contract), rejected (failed validation).
"""

# τ_base is the source's trust; for scientific databases this is the trust in METADATA,
# a specific paper's trust is computed separately: τ_paper = f(citations, journal).
SOURCES = {
    # ── tier 1: human fact-checks (direct) ────────────────────────────────
    "claimreview_google": {
        "name": "Google Fact Check Tools (ClaimReview)", "tier": "human_factcheck",
        "k_tier": 1.0, "tau": 0.9, "status": "ok",
        "api": "v1alpha1/claims:search", "access": "free-with-key",
        "key_env": "VFC_FACTCHECK_KEY", "limits": "~10k/день",
        "notes": "живой в системе; RU-покрытие мало"},
    "claimreview_dump": {
        "name": "Дамп ClaimReview (MartinoMensio)", "tier": "human_factcheck",
        "k_tier": 1.0, "tau": 0.9, "status": "ok",
        "api": "github.com/MartinoMensio/claimreview-data", "access": "free-no-key",
        "limits": "ежедневные релизы, офлайн", "notes": "замена живых квот Google"},
    # ── tier 2: scientific databases (indirect evidence) ──────────────────
    "europe_pmc": {
        "name": "Europe PMC", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "tau_paper": "citedByCount", "access": "free-no-key",
        "api": "ebi.ac.uk/europepmc/webservices/rest/search",
        "limits": "док. лимитов нет", "meta": ["citedByCount", "journalTitle", "pubYear", "abstract"],
        "notes": "лучший баланс: цитирования+журнал+год без ключа, 1.4с"},
    "openalex": {
        "name": "OpenAlex", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "tau_paper": "cited_by_count", "access": "free-with-key (VFC_OPENALEX_KEY)",
        "api": "api.openalex.org/works", "limits": "анонимно ~100 поисков/день; ключ ×10",
        "meta": ["cited_by_count", "publication_year", "primary_location.source"],
        "notes": "CC0, коммерческое использование ок; ключ — приоритет запроса"},
    "crossref": {
        "name": "Crossref", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "tau_paper": "is-referenced-by-count", "access": "free-no-key (mailto для polite-пула)",
        "api": "api.crossref.org/works", "limits": "1 req/s без mailto",
        "meta": ["is-referenced-by-count", "container-title", "issued"],
        "notes": "обязательный mailto-параметр в запросах"},
    "retraction_watch": {
        "name": "Retraction Watch (через Crossref)", "tier": "scientific_meta",
        "k_tier": 0.0,  # not evidence but a VETO: a retracted paper zeroes the weight
        "status": "ok", "access": "free-no-key",
        "api": "gitlab.com/crossref/retraction-watch-data (CSV 68 МБ)",
        "notes": "флаг ретракции → τ_paper := 0.05 и пометка в вердикте"},
    "pubmed": {
        "name": "PubMed E-utilities", "tier": "scientific", "k_tier": 0.7,
        "status": "ok", "access": "free-no-key",
        "api": "eutils.ncbi.nlm.nih.gov", "limits": "3 req/s",
        "meta": ["PubDate", "Source"], "notes": "цитирований нет — добирать Europe PMC по PMID"},
    "arxiv": {
        "name": "arXiv API", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "access": "free-no-key", "limits": "1 req/3s",
        "meta": ["published"], "notes": "препринты: τ × 0.8 (нет рецензии)"},
    # ── tier 3: encyclopedic and reference facts ──────────────────────────
    "wikipedia": {
        "name": "Wikipedia (ru/en)", "tier": "encyclopedic", "k_tier": 0.6,
        "status": "ok", "tau": 0.7, "access": "free-no-key",
        "api": "{lang}.wikipedia.org/w/api.php", "limits": "этикет, User-Agent обязателен"},
    "wikidata": {
        "name": "Wikidata SPARQL", "tier": "encyclopedic", "k_tier": 0.6,
        "status": "ok", "tau": 0.7, "access": "free-no-key",
        "api": "query.wikidata.org/sparql", "limits": "60с таймаут, 5 параллельных"},
    # ── tier 4: statistics (exact figures) ────────────────────────────────
    "worldbank": {
        "name": "World Bank API", "tier": "statistical", "k_tier": 0.9,
        "status": "ok", "tau": 1.0, "access": "free-no-key",
        "api": "api.worldbank.org/v2", "notes": "ловушка: неверный код индикатора = HTTP 200 с ошибкой внутри JSON — парсить message"},
    "who_gho": {
        "name": "WHO GHO (OData)", "tier": "statistical", "k_tier": 0.9,
        "status": "ok", "tau": 1.0, "access": "free-no-key", "api": "ghoapi.azureedge.net/api"},
    "owid": {
        "name": "Our World in Data (grapher csv/json)", "tier": "statistical",
        "k_tier": 0.9, "status": "ok", "tau": 0.9, "access": "free-no-key",
        "api": "ourworldindata.org/grapher/<slug>.csv", "notes": "мета источников включена, CC BY 4.0"},
    "eurostat": {
        "name": "Eurostat API", "tier": "statistical", "k_tier": 0.9,
        "status": "ok", "tau": 0.95, "access": "free-no-key"},
    # ── tier 5: web search (sonar / future replacements) ──────────────────
    "sonar_bothub": {
        "name": "Perplexity sonar (bothub)", "tier": "web_search", "k_tier": 0.8,
        "status": "ok", "tau": "домены из trust.py", "access": "в системе",
        "notes": "96% текущих расходов; кандидат на замещение Serper+deepseek"},
    "serper": {
        "name": "Serper.dev", "tier": "web_search_infra", "k_tier": 0.0,
        "status": "ok", "access": "free-with-key (VFC_SERPER_KEY)",
        "limits": "тариф провайдера ~$1/1k",
        "notes": "провайдер валидирован"},
    # ── keys that need to be requested from providers ──────────────────────
    "semantic_scholar": {
        "name": "Semantic Scholar", "tier": "scientific", "k_tier": 0.7,
        "status": "backlog", "access": "отказ 2026-10-29, без ключа 429",
        "notes": "БЕЗ ключа 429 постоянно (валидация провалена); с ключом 1 req/s"},
    "mbfc": {
        "name": "MBFC через RapidAPI", "tier": "trust_rating", "k_tier": 0.0,
        "status": "paid-small", "access": "$10/мес 100 req / $40 10k",
        "notes": "данные рейтингов для τ новостных доменов; оплата зарубежной картой"},
    # ── rejected ──────────────────────────────────────────────────────────
    "gdelt": {
        "name": "GDELT DOC 2.0", "tier": "news", "k_tier": 0.4,
        "status": "rejected", "notes": "429 на все попытки даже через прокси"},
}

# claim category → preferred sources (order = polling priority)
CATEGORY_ROUTES = {
    "медицина": ["claimreview_google", "claimreview_dump", "europe_pmc", "pubmed", "wikipedia"],
    "наука": ["claimreview_google", "claimreview_dump", "openalex", "europe_pmc", "arxiv"],
    "число": ["claimreview_google", "worldbank", "owid", "eurostat", "who_gho"],
    "история": ["claimreview_google", "claimreview_dump", "wikipedia", "wikidata"],
    "экономика": ["claimreview_google", "worldbank", "owid", "wikipedia"],
    "другое": ["claimreview_google", "claimreview_dump", "wikipedia"],
}

ACCESS_REQUEST_LIST = [
    # all requested keys received (2026-10-29): OpenAlex, Serper; S2 — denied, backlog
]


def tier_weight(source_id: str) -> float:
    return SOURCES[source_id].get("k_tier", 0.0)


def route_for(category: str) -> list[str]:
    return CATEGORY_ROUTES.get(category, CATEGORY_ROUTES["другое"])
