"""Pay-per-use: quota, credits, settle order, mock top-up (docs/billing-auth.md)."""
from videofactcheck import config, store


def test_new_account_gets_free_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    a = store.get_or_create_account("install-1")
    assert a["free_left_today"] == store.FREE_DAILY and a["credits"] == 0


def test_settle_free_first_then_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    store.topup("install-2", 5)
    a = store.settle("install-2", store.FREE_DAILY + 3)  # quota + 3 credit units
    assert a["free_left_today"] == 0
    assert a["credits"] == 2  # 5 - 3
    assert store.budget("install-2") == 2


def test_settle_never_negative(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    a = store.settle("install-3", 99)
    assert a["credits"] == 0 and a["free_left_today"] == 0


def test_topup_mock_adds_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    a = store.topup("install-4", 100)
    assert a["credits"] == 100
    assert store.topup("install-4", 99999)["credits"] == 100 + 10000  # mock top-up cap


def test_free_quota_resets_next_day(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    store.settle("install-5", store.FREE_DAILY)  # drain the quota
    # shift "today" to tomorrow
    import datetime as dt
    class FakeDate(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2031, 1, 2)
    orig = store.datetime
    class FakeDT:
        @staticmethod
        def now(tz=None):
            return dt.datetime(2031, 1, 2, 12, 0, tzinfo=dt.timezone.utc)
    store.datetime = FakeDT
    try:
        a = store.get_or_create_account("install-5")
        assert a["free_left_today"] == store.FREE_DAILY
    finally:
        store.datetime = orig
