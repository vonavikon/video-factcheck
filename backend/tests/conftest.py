"""Сюита обязана оставаться офлайн: офлайн-гарантия не должна держаться на
случайности (короткие цитаты старых тестов). Любая попытка реального
исходящего соединения — ошибка теста, а не тихий сетевой вызов."""
import socket

import pytest


@pytest.fixture(autouse=True)
def _no_outbound_sockets(monkeypatch):
    """Block socket-level connects for every test (DNS/HTTP мокаются явно)."""
    def _blocked(*args, **kwargs):
        raise AssertionError(
            f"real network connection attempted: {args[:1] if args else kwargs}")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
