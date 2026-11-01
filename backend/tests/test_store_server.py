"""Storage and server scenarios: run lifecycle, origin protection."""
from videofactcheck import config, server, store


def test_run_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    run_id = store.new_run("", "https://youtube.com/watch?v=x")
    store.update_run(run_id, status="done", phase="done", summary={"counts": {}})
    st = server.run(run_id)
    assert st["status"] == "done" and st["run_id"] == run_id


def test_error_run_surfaces_message(tmp_path, monkeypatch):
    """CR-SRV-01: a failed run surfaces a comprehensible error in the status, not silence."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    run_id = store.new_run("", "url")
    store.update_run(run_id, status="error", error="нет субтитров")
    st = server.run(run_id)
    assert st["status"] == "error" and st["error"] == "нет субтитров"


def test_unknown_run_reports_error():
    st = server.run("no-such-run")
    assert "error" in st


def test_origin_allowed():
    """AD-SRV-01: a foreign site cannot start runs through the browser."""
    oa = server._origin_allowed
    assert oa("https://www.youtube.com")
    assert oa("https://youtube.com/")
    assert not oa("https://evil.example.com")
    assert not oa("https://youtube.com.evil.ru")
    assert not oa("https://vk.com")
