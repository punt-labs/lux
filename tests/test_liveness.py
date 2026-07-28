"""Unit tests for punt_lux.domain.hub.liveness — the display keepalive."""

from __future__ import annotations

import errno
import threading
import time

import pytest

from punt_lux.domain.hub.liveness import DisplayLiveness, KeepaliveConnection
from punt_lux.protocol import PongMessage


class _FakeConnection:
    """A connection whose ``ping`` replays a scripted sequence of outcomes.

    Each entry is a ``PongMessage`` (a live pong), ``None`` (unresponsive), or an
    ``OSError`` (a dead socket surfacing on the send). The last entry repeats once
    the script is exhausted, so a reconnected connection keeps answering.
    """

    _results: list[PongMessage | None | OSError]

    def __new__(cls, results: list[PongMessage | None | OSError]) -> _FakeConnection:
        self = super().__new__(cls)
        self._results = results
        return self

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        result = self._results[0] if len(self._results) == 1 else self._results.pop(0)
        if isinstance(result, OSError):
            raise result
        return result


class _FakeClients:
    """A keepalive client provider counting ``get``/``drop`` against a connection."""

    _connection: KeepaliveConnection
    get_calls: int
    drop_calls: int

    def __new__(cls, connection: KeepaliveConnection) -> _FakeClients:
        self = super().__new__(cls)
        self._connection = connection
        self.get_calls = 0
        self.drop_calls = 0
        return self

    def get(self) -> KeepaliveConnection:
        self.get_calls += 1
        return self._connection

    def drop(self) -> None:
        self.drop_calls += 1


def _pong() -> PongMessage:
    return PongMessage(ts=1.0, display_ts=2.0)


class TestCheckOnce:
    """One liveness cycle: a live ping is a no-op, a failed one reconnects."""

    def test_live_ping_does_not_drop(self) -> None:
        clients = _FakeClients(_FakeConnection([_pong()]))
        DisplayLiveness(clients).check_once()
        assert clients.drop_calls == 0
        assert clients.get_calls == 1  # one probe, no reconnect

    def test_unresponsive_ping_drops_and_reconnects(self) -> None:
        # First ping unresponsive, then a pong once reconnected.
        clients = _FakeClients(_FakeConnection([None, _pong()]))
        DisplayLiveness(clients).check_once()
        assert clients.drop_calls == 1  # the dead connection was dropped
        assert clients.get_calls == 2  # ...and reconnected in the same cycle

    def test_dead_socket_ping_drops_and_reconnects(self) -> None:
        # An OSError on the ping send is a dead socket, not an escape.
        clients = _FakeClients(
            _FakeConnection([OSError(errno.EPIPE, "broken pipe"), _pong()])
        )
        DisplayLiveness(clients).check_once()
        assert clients.drop_calls == 1
        assert clients.get_calls == 2


class TestWorkerLifecycle:
    """The worker starts, ticks, and stops cleanly."""

    def test_start_is_idempotent_and_stop_joins(self) -> None:
        clients = _FakeClients(_FakeConnection([_pong()]))
        worker = DisplayLiveness(clients, interval=0.01)
        worker.start()
        worker.start()  # idempotent — no second thread
        worker.stop()
        # A stopped worker leaves no running thread behind.
        assert threading.active_count() >= 1

    @pytest.mark.slow
    def test_running_worker_probes_within_a_few_intervals(self) -> None:
        # A small interval bounds the silent window: the worker probes on its own.
        clients = _FakeClients(_FakeConnection([_pong()]))
        worker = DisplayLiveness(clients, interval=0.02)
        worker.start()
        try:
            deadline = time.monotonic() + 2.0
            while clients.get_calls == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert clients.get_calls >= 1  # the loop pinged without any external push
        finally:
            worker.stop()
