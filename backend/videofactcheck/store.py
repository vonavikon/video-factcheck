"""Storage (В21): a single SQLite, everything keyed by run_id, versioned schema."""
import contextlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, video_id TEXT, url TEXT, title TEXT, install_id TEXT DEFAULT '',
  status TEXT, phase TEXT, created TEXT, updated TEXT,
  summary TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS transcripts (
  video_id TEXT PRIMARY KEY, lang TEXT, sub_kind TEXT,
  duration REAL, cues TEXT, fetched TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  run_id TEXT, hash TEXT, quote TEXT, claim TEXT,
  t_start REAL, t_end REAL, type TEXT, category TEXT,
  verdict TEXT, why TEXT, result TEXT, sources TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);
CREATE TABLE IF NOT EXISTS accounts (
  install_id TEXT PRIMARY KEY, email TEXT, credits INTEGER DEFAULT 0,
  free_day TEXT, free_used INTEGER DEFAULT 0, created TEXT
);
CREATE TABLE IF NOT EXISTS skips (run_id TEXT, quote TEXT, reason TEXT);
"""

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()  # init per DB path, not per process: tests override DB_PATH


def _init_db(db_path: str, con: sqlite3.Connection) -> None:
    # schema and migrations — once per DB file, not on every connect (review P1-1):
    # executescript/ALTER on the hot path hit "database is locked" under load
    with _init_lock:
        if db_path in _initialized_paths:
            return
        con.executescript(_DDL)
        try:
            con.execute("ALTER TABLE runs ADD COLUMN install_id TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        cur = con.execute("SELECT value FROM meta WHERE key='schema_version'")
        if cur.fetchone() is None:
            con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION)))
        con.commit()
        _initialized_paths.add(db_path)


def connect():
    # context manager: with connect() as con — commit + GUARANTEED close
    # (a bare sqlite3 context manager closes the transaction but not the connection —
    # review P1-1: a descriptor leak on every update_run/poll). WAL + timeout
    # keep parallel runs free of "database is locked"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    _init_db(str(config.DB_PATH), con)

    @contextlib.contextmanager
    def _ctx():
        try:
            yield con
            con.commit()
        finally:
            con.close()

    return _ctx()


def new_run(video_id: str, url: str, title: str = "", install_id: str = "") -> str:
    run_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "INSERT INTO runs (run_id, video_id, url, title, status, phase, created, updated, summary, error, install_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, video_id, url, title, "running", "start", now, now, None, None, install_id),
        )
    return run_id


def update_run(run_id: str, *, status: str | None = None, phase: str | None = None,
               summary: dict | None = None, error: str | None = None, title: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sets, vals = ["updated=?"], [now]
    if status:
        sets.append("status=?"); vals.append(status)
    if phase:
        sets.append("phase=?"); vals.append(phase)
    if summary is not None:
        sets.append("summary=?"); vals.append(json.dumps(summary, ensure_ascii=False))
    if error is not None:
        sets.append("error=?"); vals.append(error)
    if title:
        sets.append("title=?"); vals.append(title)
    vals.append(run_id)
    with connect() as con:
        con.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id=?", vals)


def save_transcript(t: dict) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO transcripts VALUES (?,?,?,?,?,?)",
            (t["video_id"], t["lang"], t["sub_kind"], t["duration"],
             json.dumps(t["cues"], ensure_ascii=False), now),
        )


def load_transcript(video_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM transcripts WHERE video_id=?", (video_id,)).fetchone()
    if not row:
        return None
    return {"video_id": row["video_id"], "lang": row["lang"], "sub_kind": row["sub_kind"],
            "duration": row["duration"], "cues": json.loads(row["cues"])}


def save_claim(run_id: str, c: dict, verdict_result: dict | None) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, c["hash"], c["quote"], c["claim"], c["t_start"], c["t_end"],
             c["type"], c["category"],
             verdict_result.get("verdict") if verdict_result else None,
             verdict_result.get("why") if verdict_result else None,
             json.dumps(verdict_result, ensure_ascii=False) if verdict_result else None,
             json.dumps([], ensure_ascii=False)),
        )


def load_claims(run_id: str) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM claims WHERE run_id=? ORDER BY t_start", (run_id,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "hash": r["hash"], "quote": r["quote"], "claim": r["claim"],
            "t_start": r["t_start"], "t_end": r["t_end"],
            "type": r["type"], "category": r["category"],
            "verdict": r["verdict"], "why": r["why"],
            "result": json.loads(r["result"]) if r["result"] else None,
        })
    return out


# ── accounts and credits ──────────────────────────────
FREE_DAILY = 10


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_or_create_account(install_id: str) -> dict:
    with connect() as con:
        row = con.execute("SELECT * FROM accounts WHERE install_id=?", (install_id,)).fetchone()
        if not row:
            con.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?)",
                        (install_id, None, 0, _today(), 0,
                         datetime.now(timezone.utc).isoformat(timespec="seconds")))
            row = con.execute("SELECT * FROM accounts WHERE install_id=?", (install_id,)).fetchone()
    return _account_view(row)


def _account_view(row) -> dict:
    free_day, free_used = row["free_day"], row["free_used"] or 0
    if free_day != _today():  # new day — the quota has reset
        free_used = 0
        with connect() as con:
            con.execute("UPDATE accounts SET free_day=?, free_used=0 WHERE install_id=?",
                        (_today(), row["install_id"]))
    return {"install_id": row["install_id"], "email": row["email"],
            "credits": row["credits"] or 0,
            "free_left_today": max(0, FREE_DAILY - free_used),
            "free_daily": FREE_DAILY}


def budget(install_id: str) -> int:
    """How many machine verdicts are available (free + credits)."""
    a = get_or_create_account(install_id)
    return a["free_left_today"] + a["credits"]


def settle(install_id: str, n: int) -> dict:
    """Charge n verdicts: the daily quota first, then credits."""
    a = get_or_create_account(install_id)
    from_free = min(n, a["free_left_today"])
    from_credits = n - from_free
    with connect() as con:
        con.execute("UPDATE accounts SET free_used = free_used + ? WHERE install_id=?",
                    (from_free, install_id))
        if from_credits > 0:
            con.execute("UPDATE accounts SET credits = MAX(0, credits - ?) WHERE install_id=?",
                        (from_credits, install_id))
    return get_or_create_account(install_id)


def topup(install_id: str, credits: int) -> dict:
    """Purchase mockup: credit without payment (production version — a payment webhook)."""
    get_or_create_account(install_id)
    with connect() as con:
        con.execute("UPDATE accounts SET credits = credits + ? WHERE install_id=?",
                    (max(0, min(credits, 10000)), install_id))
    return get_or_create_account(install_id)
