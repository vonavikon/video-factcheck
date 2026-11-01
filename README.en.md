# video-factcheck

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![tests](https://github.com/vonavikon/video-factcheck/actions/workflows/tests.yml/badge.svg)](https://github.com/vonavikon/video-factcheck/actions/workflows/tests.yml)

[RU](README.md) · **EN** · [中文](README.zh.md) · [Español](README.es.md) · [Français](README.fr.md)

A Chrome extension (MV3) that fact-checks YouTube videos while you watch. It reads the subtitles straight from the page, the server pulls out checkable claims with timestamps, runs each one through human fact-checks, web search, and scientific papers, and shows the verdicts (true / false / unclear) in a panel next to the player. Clicking a timestamp jumps to the moment in the video where the claim was made; every verdict carries a source with a verbatim quote.

"Unclear" is a working verdict, not a placeholder: it marks claims where two web-search passes disagreed or the sources were not enough. The science layer is deliberately restrained: a paper can only move a verdict if it is directly on topic and recent enough, and it can never say "false": at best it downgrades "true" to "unclear".

![How it works: a fact-check panel over YouTube, claim cards with verdicts and timestamps, clicking a timestamp seeks the video, each verdict has a source with a quote and a weight](assets/concept.gif?v=v5)
Video version (10 s, silent): [how-it-works.mp4](assets/how-it-works.mp4?v=v5)

## How it works

```text
[subtitle cascade]      subtitles are read from the page; yt-dlp on the server is the fallback
        ↓
[claim extraction]      checkable facts with timestamps; opinions go to "not checkable"
        ↓
[checking, three layers in parallel]
        ├─ ClaimReview: existing human fact-checks (Google Fact Check Tools)
        ├─ sonar × 2: web search; passes disagree → "unclear"
        └─ science: Europe PMC → OpenAlex, NLI adjudication over abstracts
        ↓
[verdict fusion]        "true vs science-refutes" conflict → "unclear"
        ↓
[panel on YouTube]      cards with timestamps, sources, and source weight
```

- **Subtitle cascade.** October 2026: YouTube closed direct access to subtitles, so the extension tries routes in order: a bridge from the page world (captionTracks of the live player), `timed_text`, the "Transcript" DOM panel, and the `get_transcript` endpoint with the page's cookies. If all fail, the server fetches the subtitles via yt-dlp.
- **Claims.** An LLM labels transcript segments: verbatim quote, category, significance. Opinions, forecasts, and hyperbole go to "not checkable"; duplicates collapse by normalized hash.
- **ClaimReview.** If the claim has already been checked by humans (PolitiFact, Snopes, AFP, Provereno.media), their verdict is shown with the outlet's attribution, with no LLM call. These cards arrive first, before extraction even finishes.
- **sonar × 2.** Each fact-check runs twice through a model with built-in web search; if the passes disagree, the result is "unclear". A source is accepted only with a verbatim quote; made-up quotes get filtered out.
- **Science layer.** Europe PMC (medicine/biology, no key needed) and OpenAlex (all of science). A cheap model adjudicates the relation between established knowledge and the claim over the top-3 abstracts. A paper can move a verdict only under three conditions: it is directly on topic, published in 2015 or later (or is a review/meta-analysis), and backed by a verbatim quote.
- **Fusion.** "True" contradicted by science is downgraded to "unclear" with low confidence and a merged explanation. In the other direction, science never raises a verdict.
- **Panel.** A feed of cards with a verdict filter, a verdict map on the video timeline, a confidence scale, and source weight highlights ("science", "official").

## Features

- Verdicts true / false / unclear with timestamps and a confidence scale; clicking a timestamp jumps to that moment in the video
- Science layer with relevance and freshness guards (Europe PMC → OpenAlex), adjudicated over abstracts with a mandatory verbatim quote
- Source weight highlights ("science", "official") from a domain trust registry
- RU/EN interface; the language of verdict explanations is configured separately from the interface language
- History of the last 50 checked videos, locally in your browser
- Morphing panel: collapses into a circle with a "done" badge and stays out of the way while the check runs

## Installing from source

You need Chrome/Edge 111+ and Python 3.12+. The extension is not in the Chrome Web Store; source installs only. All checks go through your own server on `127.0.0.1:8765`, with your own API keys.

### Server

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Linux/macOS: .venv/bin/pip
cd ..
cp .env.example .env
```

Fill in your keys in `.env`:

- `VFC_LLM_KEY`: key for an OpenAI-compatible provider (bothub by default: deepseek extracts claims and adjudicates NLI, sonar delivers verdicts with web search on its side). Required.
- `VFC_SERPER_KEY`: your Serper key for the search backend.
- `VFC_FACTCHECK_KEY`: Google Fact Check Tools key; without it the ClaimReview layer is simply skipped.

Europe PMC and OpenAlex work without keys. Start the server:

```bash
cd backend
.venv/Scripts/python -m videofactcheck.cli serve --port 8765
```

Without Chrome you can check a single video from the CLI: `.venv/Scripts/python -m videofactcheck.cli check "<video url>"`.

### Extension

1. Open `chrome://extensions` and enable Developer mode.
2. "Load unpacked" → the `extension` folder of this repository.
3. Open any YouTube video: a "Fact-check" panel appears on the right. Press "Check video".

Subtitles arrive in about 10 seconds, claims in 2-4 minutes for a 15-minute video; verdicts arrive as they are ready, and you don't have to wait: collapse the panel and the check continues in the background.

## Architecture

```text
extension/                    Chrome MV3
  content.js                  panel on YouTube: cards, timestamp map, morph into a circle
  page-bridge.js              script in the MAIN world: captionTracks and videoDetails of the live player
  background.js               service worker: talks to the server
  options.html, account.html  settings (language) and the 50-video history in chrome.storage
backend/                      FastAPI + CLI
  videofactcheck/transcript.py       server-side subtitle fallback: yt-dlp, VTT parser with auto-caption cleanup
  videofactcheck/claims.py           claim extraction with timestamps
  videofactcheck/factcheck_db.py     ClaimReview: existing human fact-checks
  videofactcheck/verdict.py          sonar × 2, confidence scale, fusion
  videofactcheck/plausibility.py     science layer: Europe PMC → OpenAlex, NLI with a quote
  videofactcheck/trust.py            domain trust weights (whitelist/blacklist)
  videofactcheck/store.py            SQLite: runs, verdicts, transcripts
  videofactcheck/server.py           HTTP API for the extension (127.0.0.1:8765)
  videofactcheck/cli.py              `serve` and `check <url>`
  tests/                             72 tests, pytest
```

The extension sends the server a transcript read from the page (requests to YouTube go from the user's IP, not the server's) and receives verdicts as they complete.

## Status

A pet project. Version 0.9.1 (October 2026), tested on live videos.

The project grew in iterations driven by real runs: the subtitle cascade appeared after YouTube closed direct subtitle access in October 2026; the ClaimReview conveyor (human fact-checks arrive with the first extraction batches) and the timeline stratification of verdicts came out of long runs on 40-minute interviews; the morphing panel came from one complaint: "the panel is in the way".

Limitations: videos without subtitles are rejected (automatic transcription is planned), live streams and Shorts are not supported, a single run yields at most 15 verdicts; the rest are marked "unchecked".

## License

MIT, see [LICENSE](LICENSE).
