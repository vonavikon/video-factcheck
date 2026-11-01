"""videofactcheck — fact-checking pipeline for YouTube videos.

Stages:
  0. transcript    — timestamped transcript (yt-dlp captions, whisper fallback later)
  1. claims        — extraction of checkable claims (LLM)
  2. factcheck_db  — matching against existing fact-checks (ClaimReview)
  3. search        — web search per claim
  4. verdict       — verdict voting across sources with trust weights
  5. trust         — domain trust table
  6. evals         — golden set, regression checks
  report           — per-video report for personal testing
"""

__version__ = "0.0.1"
