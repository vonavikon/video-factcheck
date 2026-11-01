"""Configuration: keys and settings from the environment / .env.

Keys are NOT stored in the repo. Variable names:
  VFC_LLM_BASE_URL   — OpenAI-compatible endpoint (default bothub)
  VFC_LLM_KEY        — LLM provider API key
  VFC_LLM_MODEL      — model for extraction/verdicts (default deepseek-v4-flash)
  VFC_SEARCH_BACKEND — cse | serper (default cse)
  VFC_CSE_KEY / VFC_CSE_CX  — Google Programmable Search
  VFC_SERPER_KEY
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))


_load_dotenv()

LLM_BASE_URL = os.environ.get("VFC_LLM_BASE_URL", "https://openai.bothub.chat/v1")
LLM_KEY = os.environ.get("VFC_LLM_KEY", "")
LLM_MODEL = os.environ.get("VFC_LLM_MODEL", "deepseek-v4-flash")

SEARCH_BACKEND = os.environ.get("VFC_SEARCH_BACKEND", "cse")
CSE_KEY = os.environ.get("VFC_CSE_KEY", "")
CSE_CX = os.environ.get("VFC_CSE_CX", "")
SERPER_KEY = os.environ.get("VFC_SERPER_KEY", "")

DATA_DIR = Path(os.environ.get("VFC_DATA_DIR", str(ROOT / "data")))
DB_PATH = Path(os.environ.get("VFC_DB_PATH", str(DATA_DIR / "vfc.db")))
MAX_VERDICTS_PER_RUN = int(os.environ.get("VFC_MAX_VERDICTS", "15"))
