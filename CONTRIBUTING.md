# Contributing

Issues and pull requests are welcome. The project is run by one person, so for anything larger than a small fix, open an issue first and describe what you want to change and why.

## Setup

Same as [Installing from source](README.md#installing-from-source): Python 3.12+ venv for the backend, keys in `.env`, extension loaded unpacked from `extension/`.

## Tests

Backend tests run offline: external calls (LLM, search, Europe PMC) are mocked, no keys needed.

```bash
pip install -r backend/requirements-dev.txt
pip install --no-deps -e ./backend
pytest backend/tests -q
```

CI runs the same command on every push and pull request; keep it green.

## Useful contributions

- Bug reports with a YouTube URL where the extension misbehaved, and what you expected instead.
- Claims that got "unclear" but have a known human fact-check: these examples show where the pipeline misses.
- Fixes with a test that reproduces the bug first.

## Discuss first

- New verdict sources: each one changes latency, cost, and trust weighting.
- Changes to the fusion rules: they are tuned on real long runs, and a "simpler" rule usually loses information.

## Commit style

`area: what changed`, lowercase, for example `transcript: fix VTT parsing of auto-captions`.
