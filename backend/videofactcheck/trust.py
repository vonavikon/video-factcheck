"""Stage 5 (reduced scope): domain trust, whitelist/blacklist + unknown=0.5.

The full MBFC/WP:RSP lists are a later iteration. The starter list is ~40
domains, RU+EN.
"""
from . import config

WHITELIST: dict[str, float] = {
    # international agencies and fact-checking
    "reuters.com": 1.0, "apnews.com": 1.0, "bbc.com": 0.9, "bbc.co.uk": 0.9,
    "factcheck.org": 1.0, "politifact.com": 1.0, "snopes.com": 0.9,
    "fullfact.org": 1.0, "apnews.com": 1.0, "afp.com": 0.9,
    # science and medicine
    "who.int": 1.0, "nih.gov": 1.0, "ncbi.nlm.nih.gov": 1.0, "cochrane.org": 1.0,
    "nature.com": 0.9, "science.org": 0.9, "thelancet.com": 0.9,
    "nejm.org": 0.9, "bmj.com": 0.9, "pubmed.ncbi.nlm.nih.gov": 1.0,
    "nasa.gov": 1.0, "noaa.gov": 0.9, "ourworldindata.org": 0.9,
    # encyclopedias/data
    "wikipedia.org": 0.7, "britannica.com": 0.8, "statista.com": 0.7,
    # primary sources of talks/universities
    "ted.com": 0.85, "harvard.edu": 0.85, "mit.edu": 0.85, "stanford.edu": 0.85,
    # government statistics
    "rosstat.gov.ru": 0.8, "census.gov": 0.9, "bls.gov": 0.9,
    # quality Russian-language outlets
    "nplus1.ru": 0.8, "tass.ru": 0.7, "rbc.ru": 0.7, "kommersant.ru": 0.7,
    "meduza.io": 0.6, "nauka.tv": 0.6, "postnauka.ru": 0.7,
    "provereno.media": 0.9, "lapshemonitor.org": 0.8,
}
BLACKLIST: dict[str, float] = {
    "naturalnews.com": 0.1, "worldtruth.tv": 0.1, "infowars.com": 0.1,
    "ren.tv": 0.3, "vk.com": 0.2, "dzen.ru": 0.2, "yandex.ru": 0.4,
    "pikabu.ru": 0.2, "sovetday.ru": 0.1,
}
UNKNOWN = 0.5


def domain_trust(domain: str) -> float:
    d = domain.lower().removeprefix("www.")
    for k, v in BLACKLIST.items():
        if d == k or d.endswith("." + k):
            return v
    for k, v in WHITELIST.items():
        if d == k or d.endswith("." + k):
            return v
    return UNKNOWN
