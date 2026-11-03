"""Registry of verification sources with weights (the system's shared dataset).

Research and live validation: 2026-10-29 (landscape survey + API probes).
Weight math, docs/verdict-math.md: evidence enters the Bayesian accumulator
as Δlogit = k_tier * τ_source * stance; τ of papers depends on citations.

Tiers (k_tier): direct human fact-checks 1.0; statistics for an exact figure
0.9; direct confirmation by a reliable source via the web 0.8; a scientific
paper (indirect) 0.7; encyclopedic 0.6; news without a verification status 0.4.
Validation statuses: ok (live request 2026-10-29), key (works / a key needs
requesting), paid (commercial contract), rejected (failed validation).
"""

# τ_base is the trust in a source; for scientific databases this is trust in
# METADATA, trust in a specific paper is computed separately:
# τ_paper = f(citations, journal).
SOURCES = {
    # ── tier 1: human fact-checks (direct) ────────────────────────────────
    "claimreview_google": {
        "name": "Google Fact Check Tools (ClaimReview)", "tier": "human_factcheck",
        "k_tier": 1.0, "tau": 0.9, "status": "ok",
        "api": "v1alpha1/claims:search", "access": "free-with-key",
        "key_env": "VFC_FACTCHECK_KEY", "limits": "~10k/day",
        "notes": "live in the system; RU coverage is small"},
    "claimreview_dump": {
        "name": "ClaimReview dump (MartinoMensio)", "tier": "human_factcheck",
        "k_tier": 1.0, "tau": 0.9, "status": "ok",
        "api": "github.com/MartinoMensio/claimreview-data", "access": "free-no-key",
        "limits": "daily releases, offline", "notes": "replaces Google's live quotas"},
    # ── tier 2: scientific databases (indirect evidence) ──────────────────
    "europe_pmc": {
        "name": "Europe PMC", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "tau_paper": "citedByCount", "access": "free-no-key",
        "api": "ebi.ac.uk/europepmc/webservices/rest/search",
        "limits": "no documented limits", "meta": ["citedByCount", "journalTitle", "pubYear", "abstract"],
        "notes": "best balance: citations+journal+year without a key, 1.4s"},
    "openalex": {
        "name": "OpenAlex", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "tau_paper": "cited_by_count", "access": "free-with-key (VFC_OPENALEX_KEY)",
        "api": "api.openalex.org/works", "limits": "anonymous ~100 searches/day; key x10",
        "meta": ["cited_by_count", "publication_year", "primary_location.source"],
        "notes": "CC0, commercial use ok; a key gives request priority"},
    "crossref": {
        "name": "Crossref", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "tau_paper": "is-referenced-by-count", "access": "free-no-key (mailto for the polite pool)",
        "api": "api.crossref.org/works", "limits": "1 req/s without mailto",
        "meta": ["is-referenced-by-count", "container-title", "issued"],
        "notes": "the mailto parameter is mandatory in requests"},
    "retraction_watch": {
        "name": "Retraction Watch (via Crossref)", "tier": "scientific_meta",
        "k_tier": 0.0,  # not evidence but a VETO: a retracted paper zeroes the weight
        "status": "ok", "access": "free-no-key",
        "api": "gitlab.com/crossref/retraction-watch-data (CSV 68 MB)",
        "notes": "retraction flag -> τ_paper := 0.05 plus a note in the verdict"},
    "pubmed": {
        "name": "PubMed E-utilities", "tier": "scientific", "k_tier": 0.7,
        "status": "ok", "access": "free-no-key",
        "api": "eutils.ncbi.nlm.nih.gov", "limits": "3 req/s",
        "meta": ["PubDate", "Source"], "notes": "no citation counts: fetch Europe PMC by PMID"},
    "arxiv": {
        "name": "arXiv API", "tier": "scientific", "k_tier": 0.7, "status": "ok",
        "access": "free-no-key", "limits": "1 req/3s",
        "meta": ["published"], "notes": "preprints: τ x 0.8 (no peer review)"},
    # ── tier 3: encyclopedic and factual ──────────────────────────────────
    "wikipedia": {
        "name": "Wikipedia (ru/en)", "tier": "encyclopedic", "k_tier": 0.6,
        "status": "ok", "tau": 0.7, "access": "free-no-key",
        "api": "{lang}.wikipedia.org/w/api.php", "limits": "etiquette, User-Agent required"},
    "wikidata": {
        "name": "Wikidata SPARQL", "tier": "encyclopedic", "k_tier": 0.6,
        "status": "ok", "tau": 0.7, "access": "free-no-key",
        "api": "query.wikidata.org/sparql", "limits": "60s timeout, 5 concurrent"},
    # ── tier 4: statistics (exact figures) ────────────────────────────────
    "worldbank": {
        "name": "World Bank API", "tier": "statistical", "k_tier": 0.9,
        "status": "ok", "tau": 1.0, "access": "free-no-key",
        "api": "api.worldbank.org/v2", "notes": "gotcha: a wrong indicator code = HTTP 200 with an error inside the JSON; parse message"},
    "who_gho": {
        "name": "WHO GHO (OData)", "tier": "statistical", "k_tier": 0.9,
        "status": "ok", "tau": 1.0, "access": "free-no-key", "api": "ghoapi.azureedge.net/api"},
    "owid": {
        "name": "Our World in Data (grapher csv/json)", "tier": "statistical",
        "k_tier": 0.9, "status": "ok", "tau": 0.9, "access": "free-no-key",
        "api": "ourworldindata.org/grapher/<slug>.csv", "notes": "source metadata included, CC BY 4.0"},
    "eurostat": {
        "name": "Eurostat API", "tier": "statistical", "k_tier": 0.9,
        "status": "ok", "tau": 0.95, "access": "free-no-key"},
    # ── tier 5: web search (sonar / future replacements) ──────────────────
    "sonar_bothub": {
        "name": "Perplexity sonar (bothub)", "tier": "web_search", "k_tier": 0.8,
        "status": "ok", "tau": "domains from trust.py", "access": "in use",
        "notes": "96% of current spend; a candidate for replacement by Serper+deepseek"},
    "serper": {
        "name": "Serper.dev", "tier": "web_search_infra", "k_tier": 0.0,
        "status": "ok", "access": "free-with-key (VFC_SERPER_KEY)",
        "limits": "$1/1k, starter credits",
        "notes": "key obtained and verified by a live request 2026-10-29; the base of the Serper+deepseek hybrid (sonar replacement)"},
    # ── access requests (pending decisions) ──────────────────────────────
    "semantic_scholar": {
        "name": "Semantic Scholar", "tier": "scientific", "k_tier": 0.7,
        "status": "backlog", "access": "refused 2026-10-29, 429 without a key",
        "notes": "without a key: constant 429 (validation failed); with a key 1 req/s"},
    "mbfc": {
        "name": "MBFC via RapidAPI", "tier": "trust_rating", "k_tier": 0.0,
        "status": "paid-small", "access": "$10/mo 100 req / $40 10k",
        "notes": "rating data for τ of news domains; payment with a foreign card"},
    # ── rejected ──────────────────────────────────────────────────────────
    "gdelt": {
        "name": "GDELT DOC 2.0", "tier": "news", "k_tier": 0.4,
        "status": "rejected", "notes": "429 on every attempt, even via a proxy"},
}

# claim category -> preferred sources (order = polling priority).
# Keys mirror the Russian category values the claim extractor actually emits
# (claims.py: "медицина", "наука", "число", "история", "экономика", "другое").
CATEGORY_ROUTES = {
    "медицина": ["claimreview_google", "claimreview_dump", "europe_pmc", "pubmed", "wikipedia"],
    "наука": ["claimreview_google", "claimreview_dump", "openalex", "europe_pmc", "arxiv"],
    "число": ["claimreview_google", "worldbank", "owid", "eurostat", "who_gho"],
    "история": ["claimreview_google", "claimreview_dump", "wikipedia", "wikidata"],
    "экономика": ["claimreview_google", "worldbank", "owid", "wikipedia"],
    "другое": ["claimreview_google", "claimreview_dump", "wikipedia"],
}

ACCESS_REQUEST_LIST = [
    # all requested keys obtained (2026-10-29): OpenAlex, Serper; S2 refused, backlog
]


def tier_weight(source_id: str) -> float:
    return SOURCES[source_id].get("k_tier", 0.0)


def route_for(category: str) -> list[str]:
    return CATEGORY_ROUTES.get(category, CATEGORY_ROUTES["другое"])
