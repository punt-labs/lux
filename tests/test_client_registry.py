"""``ClientRegistry.with_reconnect`` restores listener after reconnect.

Bugbot MED 1: the original ``with_reconnect`` reconnected the socket but
never restarted the background listener. Push-mode callers (callbacks
registered via ``on_event``, ``poll_event`` blocked on
``_event_queue``) silently stopped receiving frames after the first
``OSError`` recovered by the registry — the socket was healthy, the
listener thread was dead.
"""

from __future__ import annotations

from typing import Self

import pytest

from punt_lux.domain.hub.clients import ClientRegistry


class _FakeClient:
    """Records connect / close / start_listener calls on a real client surface."""

    connect_calls: int
    close_calls: int
    start_listener_calls: int
    _fail_first_call: bool

    def __new__(cls, *, fail_first_call: bool = False) -> Self:
        self = super().__new__(cls)
        self.connect_calls = 0
        self.close_calls = 0
        self.start_listener_calls = 0
        self._fail_first_call = fail_first_call
        return self

    def connect(self) -> None:
        self.connect_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def start_listener(self) -> None:
        self.start_listener_calls += 1


def _install_client(registry: ClientRegistry, fake: _FakeClient) -> None:
    """Plant ``fake`` into ``registry`` so ``with_reconnect`` finds it."""
    registry._client = fake  # type: ignore[assignment]  # test-only duck type


def test_with_reconnect_restarts_listener_after_oserror() -> None:
    """A successful reconnect must restart the background listener."""
    registry = ClientRegistry()
    fake = _FakeClient()
    _install_client(registry, fake)

    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BrokenPipeError("simulated socket loss")
        return "ok"

    result = registry.with_reconnect(fn)

    assert result == "ok"
    assert fake.close_calls == 1
    assert fake.connect_calls == 1
    assert fake.start_listener_calls == 1


def test_with_reconnect_no_listener_restart_on_happy_path() -> None:
    """If ``fn`` succeeds, no reconnect cycle runs."""
    registry = ClientRegistry()
    fake = _FakeClient()
    _install_client(registry, fake)

    result = registry.with_reconnect(lambda: "ok")

    assert result == "ok"
    assert fake.close_calls == 0
    assert fake.connect_calls == 0
    assert fake.start_listener_calls == 0


def test_with_reconnect_wraps_reconnect_failure() -> None:
    """A failed reconnect raises ``RuntimeError`` chained from the original."""
    registry = ClientRegistry()

    class _UnreconnectableClient(_FakeClient):
        def connect(self) -> None:
            raise OSError("reconnect refused")

    fake = _UnreconnectableClient()
    _install_client(registry, fake)

    def fn() -> str:
        raise ConnectionResetError("simulated socket loss")

    with pytest.raises(RuntimeError, match="Reconnect failed"):
        registry.with_reconnect(fn)
    assert fake.start_listener_calls == 0
