"""videofactcheck: a fact-checking pipeline for YouTube videos.

Stages (see docs/pipeline-spec.md):
  0. transcript:    transcript with timecodes (yt-dlp captions, whisper fallback later)
  1. claims:        extraction of checkable claims (LLM)
  2. factcheck_db:  matching against ready fact-checks (ClaimReview)
  3. search:        web search per claim
  4. verdict:       source voting for the verdict with trust weights
  5. trust:         domain trust table
  6. evals:         golden set, regressions
  report:           per-video report for personal testing
"""

__version__ = "0.0.1"
