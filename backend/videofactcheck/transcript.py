"""Stage 0: timestamped transcript via yt-dlp captions (decisions В6–В8).

Minimal own VTT parser that strips rolling duplicates from auto-subs —
timestamps are untouched, only text is cleaned (В8). Whisper fallback is planned for iteration 2.
"""
import re
import subprocess
import sys
from pathlib import Path

from . import config

TS = re.compile(r"(\d+):(\d+):(\d+)[.,](\d+)")
TAGS = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def _ytdlp_base() -> list[str]:
    """yt-dlp + proxy from VFC_YTDLP_PROXY (e.g. a local SOCKS tunnel)."""
    import os
    proxy = os.environ.get("VFC_YTDLP_PROXY", "")
    base = ["yt-dlp", "--no-update", "--skip-download"]
    if proxy:
        base += ["--proxy", proxy]
    return base


def _sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def fetch(url: str, langs: str = "ru,ru-orig,en,en-orig") -> dict:
    """Downloads subtitles (manual first, then auto-subs) → metadata + cues."""
    # СЕК-6: YouTube-watch URLs only (anti-SSRF for yt-dlp)
    from urllib.parse import urlparse
    _p = urlparse(url if "://" in url else "https://" + url)
    if not (_p.netloc == "youtube.com" or _p.netloc.endswith(".youtube.com")
            or _p.netloc == "youtu.be" or _p.netloc.endswith(".youtu.be")):
        raise RuntimeError("поддерживаются только ссылки на YouTube")
    out_dir = config.DATA_DIR / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "fetch"
    tmp.mkdir(exist_ok=True)
    meta = subprocess.run(
        _ytdlp_base() + ["--print",
         "%(id)s|||%(title)s|||%(duration)s", url],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if meta.returncode != 0 or "|||" not in meta.stdout:
        raise RuntimeError("yt-dlp не отдал данные видео (подробности в логе сервера)")
    lines_out = [ln for ln in meta.stdout.strip().splitlines() if "|||" in ln]
    if len(lines_out) > 1:
        raise RuntimeError(
            f"Ссылка ведёт не к одному видео: {len(lines_out)} записей, "
            "похоже на плейлист. Дай URL конкретного видео"
        )
    vid, title, duration = lines_out[0].split("|||")[:3]

    dl_error = ""
    for kind, flag in (("manual", ["--write-subs"]), ("auto", ["--write-auto-subs"])):
        for f in tmp.glob(f"{vid}*"):
            f.unlink()
        dl = subprocess.run(
            _ytdlp_base() + flag + ["--sub-langs", langs, "--convert-subs", "vtt",
             "-o", str(tmp / "%(id)s"), url],
            capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        files = sorted(tmp.glob(f"{vid}*.vtt"))
        if files:
            cues = _parse_vtt(files[-1])
            if cues:
                lang = "ru" if ".ru" in files[-1].name else "en"
                return {
                    "video_id": vid, "title": title,
                    "duration": float(duration or 0),
                    "lang": lang, "sub_kind": kind, "cues": cues,
                }
        # yt-dlp failed (429 from YouTube on a datacenter IP etc.) — this is not "no subs"
        if dl.returncode != 0 or "429" in dl.stderr or "Too Many Requests" in dl.stderr:
            import sys
            print(f"[transcript:err] yt-dlp: {dl.stderr.strip()[:400]}", file=sys.stderr)
            dl_error = "ytdlp_failed"
    if dl_error:
        raise RuntimeError(
            "Субтитры не скачались (YouTube ограничил запросы). "
            "Запусти проверку кнопкой на странице видео")
    raise RuntimeError("На видео нет субтитров, проверить не получится")


def _parse_vtt(path: Path) -> list[dict]:
    """VTT → cues [{start,end,text}]. Block parsing per the WebVTT spec:
    a cue block = optional identifier line + timing line + text up to a blank
    line; the identifier is discarded (test TR: "1", "2" must not stick
    to the previous cue's text). Rolling duplicates from auto-subs are removed after.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    # cut off the WEBVTT header and metadata up to the first blank line
    body = text.split("\n\n", 1)[1] if text.startswith("WEBVTT") else text
    cues: list[dict] = []
    for block in body.split("\n\n"):
        lines = [ln.strip("\r") for ln in block.strip().splitlines() if ln.strip()]
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ts_idx is None:
            continue  # block without timing — note/style/orphan identifier
        m = TS.search(lines[ts_idx])
        if not m:
            continue
        parts = lines[ts_idx].split("-->")
        a, b = TS.search(parts[0]), TS.search(parts[1])
        if not (a and b):
            continue
        start = _sec(a.group(1), a.group(2), a.group(3), a.group(4))
        end = _sec(b.group(1), b.group(2), b.group(3), b.group(4))
        body_lines = [TAGS.sub("", ln).strip() for ln in lines[ts_idx + 1:]]
        cue_text = " ".join(t for t in body_lines if t and t != "&nbsp;")
        if not cue_text:
            continue
        # rolling repeats: same text, or contained in the previous cue
        prev = cues[-1]["text"] if cues else ""
        if cue_text == prev or (prev and cue_text in prev):
            continue
        if prev and prev in cue_text:
            cues[-1]["text"] = cue_text  # auto-subs extend the line — keep the full one
            cues[-1]["end"] = max(cues[-1]["end"], end)
            continue
        cues.append({"start": start, "end": end, "text": cue_text})

    # collapse consecutive cues with identical text
    out: list[dict] = []
    for c in cues:
        if out and out[-1]["text"] == c["text"]:
            out[-1]["end"] = max(out[-1]["end"], c["end"])
            continue
        out.append(c)
    return out


def to_segments(cues: list[dict], max_chars: int = 220, max_gap: float = 2.5) -> list[dict]:
    """Cues → LLM segments: [{id, t_start, t_end, text}] (~1-2 sentences)."""
    segs: list[dict] = []
    cur: dict = {}
    for c in cues:
        if not cur:
            cur = {"t_start": c["start"], "t_end": c["end"], "text": c["text"]}
            continue
        gap = c["start"] - cur["t_end"]
        if gap > max_gap or len(cur["text"]) + len(c["text"]) > max_chars:
            segs.append(cur)
            cur = {"t_start": c["start"], "t_end": c["end"], "text": c["text"]}
        else:
            cur["text"] = f"{cur['text']} {c['text']}".strip()
            cur["t_end"] = c["end"]
    if cur:
        segs.append(cur)
    for i, s in enumerate(segs):
        s["id"] = i
    return segs


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


if __name__ == "__main__":
    data = fetch(sys.argv[1])
    print(f"{data['title']} [{data['sub_kind']}/{data['lang']}] cues={len(data['cues'])}")
    print(f"segments={len(to_segments(data['cues']))}")
