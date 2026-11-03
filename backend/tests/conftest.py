"""The suite must stay offline: the offline guarantee must not depend on
luck (short quotes in older tests). Any real outbound connection attempt
is a test failure, not a silent network call."""
import socket

import pytest


@pytest.fixture(autouse=True)
def _no_outbound_sockets(monkeypatch):
    """Block socket-level connects for every test (DNS/HTTP are explicitly mocked)."""
    def _blocked(*args, **kwargs):
        raise AssertionError(
            f"real network connection attempted: {args[:1] if args else kwargs}")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
