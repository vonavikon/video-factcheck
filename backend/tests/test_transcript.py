"""Stage 0 scenarios: the VTT parser, segments, playlist protection,
telling "no subs" apart from a download failure (429)."""
import pytest

from videofactcheck import transcript as tr


VTT = """WEBVTT

1
00:00:01.000 --> 00:00:03.000
привет всем сегодня поговорим

2
00:00:03.000 --> 00:00:05.000
привет всем сегодня поговорим

3
00:00:05.000 --> 00:00:07.000
о прокрастинации
"""


def test_rolling_dupes_removed(tmp_path):
    f = tmp_path / "t.vtt"
    f.write_text(VTT, encoding="utf-8")
    cues = tr._parse_vtt(f)
    texts = [c["text"] for c in cues]
    assert texts.count("привет всем сегодня поговорим") == 1
    assert cues[0]["start"] == 1.0 and cues[0]["end"] == 3.0


def test_inline_tags_stripped(tmp_path):
    f = tmp_path / "t.vtt"
    f.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
        "<00:00:01.000><c>слова</c> с тегами\n",
        encoding="utf-8",
    )
    cues = tr._parse_vtt(f)
    assert cues and cues[0]["text"] == "слова с тегами"


def test_comma_timestamps_and_empty(tmp_path):
    f = tmp_path / "t.vtt"
    f.write_text(
        "WEBVTT\n\n00:00:01,500 --> 00:00:02,500\nтекст\n\n00:00:03.000 --> 00:00:04.000\n\n",
        encoding="utf-8",
    )
    cues = tr._parse_vtt(f)
    assert len(cues) == 1 and cues[0]["start"] == 1.5


def test_segments_gap_split():
    cues = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 1.9, "end": 4.0, "text": "b"},
        {"start": 30.0, "end": 32.0, "text": "c"},  # gap > max_gap
    ]
    segs = tr.to_segments(cues)
    assert len(segs) == 2
    assert segs[0]["t_start"] == 0.0 and segs[1]["t_start"] == 30.0


def test_playlist_guard(monkeypatch):
    """Scenario CV-TR-01: yt-dlp returned several entries (a playlist); an honest refusal."""
    class FakeProc:
        returncode = 0
        stdout = "id1|||t1|||10\nid2|||t2|||20\n"
        stderr = ""
    monkeypatch.setattr(tr.subprocess, "run", lambda *a, **k: FakeProc())
    try:
        tr.fetch("https://youtube.com/playlist?list=x")
        raised = False
    except RuntimeError as e:
        raised = "плейлист" in str(e) or "видео" in str(e)
    assert raised


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_ytdlp(monkeypatch, results):
    """Replaces subprocess.run: results are returned in sequence
    (metadata, then the manual and auto-subs download attempts)."""
    it = iter(results)
    monkeypatch.setattr(tr.subprocess, "run", lambda *a, **k: next(it))


def test_no_subs_when_ytdlp_clean(tmp_path, monkeypatch):
    """yt-dlp exited cleanly but no sub files appeared: "no subtitles"."""
    monkeypatch.setattr(tr.config, "DATA_DIR", tmp_path)
    _fake_ytdlp(monkeypatch, [
        _Proc(stdout="vid1|||title|||10\n"),  # metadata
        _Proc(), _Proc(),  # manual and auto subs: exit 0, no files
    ])
    with pytest.raises(RuntimeError) as ei:
        tr.fetch("https://youtube.com/watch?v=vid1")
    msg = str(ei.value)
    assert "нет субтитров" in msg
    assert "не скачались" not in msg


def test_download_error_on_429(tmp_path, monkeypatch):
    """Bug scenario 2026-10-28: timed_text returns 429 from a datacenter IP.
    This is a download failure, not "the video has no subtitles", and the
    message hints at the client path (the button on the video page)."""
    monkeypatch.setattr(tr.config, "DATA_DIR", tmp_path)
    _fake_ytdlp(monkeypatch, [
        _Proc(stdout="vid1|||title|||10\n"),  # metadata downloaded
        _Proc(),  # manual subs: clean, no files
        _Proc(returncode=1, stderr="HTTP Error 429: Too Many Requests"),  # auto subs
    ])
    with pytest.raises(RuntimeError) as ei:
        tr.fetch("https://youtube.com/watch?v=vid1")
    msg = str(ei.value)
    assert "не скачались" in msg
    assert "странице видео" in msg
    assert "нет субтитров" not in msg


def test_download_error_on_ytdlp_exit(tmp_path, monkeypatch):
    """A non-zero yt-dlp exit without a 429 in stderr is also a download failure, not "no subs"."""
    monkeypatch.setattr(tr.config, "DATA_DIR", tmp_path)
    broken = _Proc(returncode=2, stderr="yt-dlp crashed")
    _fake_ytdlp(monkeypatch, [
        _Proc(stdout="vid1|||title|||10\n"), broken, broken,
    ])
    with pytest.raises(RuntimeError) as ei:
        tr.fetch("https://youtube.com/watch?v=vid1")
    assert "не скачались" in str(ei.value)


def test_client_transcript_used_as_is(tmp_path, monkeypatch):
    """Task 2: a client transcript is not overwritten; tr.fetch is never called,
    exactly the client subs end up in storage."""
    from videofactcheck import claims as claims_mod, pipeline, store

    monkeypatch.setattr(tr.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tr.config, "DB_PATH", tmp_path / "t.db")

    def _no_fetch(url):
        raise AssertionError("tr.fetch не должен вызываться при клиентском транскрипте")
    monkeypatch.setattr(pipeline.tr, "fetch", _no_fetch)
    monkeypatch.setattr(pipeline.claims_mod, "extract",
                        lambda segs, lang, **k: {"claims": [], "skipped": []})

    t = {"video_id": "vid1", "title": "T", "duration": 10.0, "lang": "en",
         "sub_kind": "client", "cues": [{"start": 0.0, "end": 2.0, "text": "hello"}]}
    url = "https://youtube.com/watch?v=vid1"
    run_id = store.new_run("", url)
    pipeline._run(run_id, url, transcript=t)

    st = pipeline.get_status(run_id)
    assert st["status"] == "done" and st["error"] is None
    saved = store.load_transcript("vid1")
    assert saved["sub_kind"] == "client" and saved["cues"][0]["text"] == "hello"
