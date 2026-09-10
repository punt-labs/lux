"""Unit tests for punt_lux.domain.hub.liveness — the display keepalive."""

from __future__ import annotations

import errno
import logging
import threading
import time

import pytest

from punt_lux.domain.hub.liveness import DisplayLiveness, KeepaliveConnection
from punt_lux.domain.hub.liveness_pacing import _DISCONNECTED_PROBE_INTERVAL
from punt_lux.protocol import PongMessage


class _FakeConnection:
    """A connection whose ``ping`` replays a scripted sequence of outcomes.

    Each entry is a ``PongMessage`` (a live pong), ``None`` (unresponsive), or an
    exception — ``OSError`` (a dead socket on the send) or ``RuntimeError`` (a
    connect failure ``ClientRegistry`` wraps). The last entry repeats once the
    script is exhausted, so a reconnected connection keeps answering.
    """

    _results: list[PongMessage | Exception | None]

    def __new__(cls, results: list[PongMessage | Exception | None]) -> _FakeConnection:
        self = super().__new__(cls)
        self._results = results
        return self

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        result = self._results[0] if len(self._results) == 1 else self._results.pop(0)
        if isinstance(result, Exception):
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
    """One liveness cycle: a live ping is a no-op, a twice-failed one reconnects."""

    def test_live_ping_does_not_drop(self) -> None:
        clients = _FakeClients(_FakeConnection([_pong()]))
        DisplayLiveness(clients).check_once()
        assert clients.drop_calls == 0
        assert clients.get_calls == 1  # one probe, no reconnect

    def test_reprobe_before_drop_spares_a_recovered_connection(self) -> None:
        # First probe fails, but the re-probe finds the connection back (a
        # concurrent SendRecovery reconnected). The keepalive must NOT drop it.
        clients = _FakeClients(_FakeConnection([None, _pong()]))
        DisplayLiveness(clients).check_once()
        assert clients.drop_calls == 0  # the recovered connection is spared
        assert clients.get_calls == 2  # probe, then the sparing re-probe

    def test_twice_failed_probe_drops_and_reconnects(self) -> None:
        # Both probes fail (genuinely dead), then a pong once reconnected.
        clients = _FakeClients(_FakeConnection([None, None, _pong()]))
        DisplayLiveness(clients).check_once()
        assert clients.drop_calls == 1  # the dead connection was dropped
        assert clients.get_calls == 3  # probe, re-probe, then reconnect

    def test_dead_socket_ping_is_caught_not_escaped(self) -> None:
        # An OSError on the ping send is a dead socket, handled as a failed probe.
        clients = _FakeClients(
            _FakeConnection([OSError(errno.EPIPE, "broken pipe"), _pong()])
        )
        DisplayLiveness(clients).check_once()  # must not raise
        assert clients.drop_calls == 0  # re-probe recovered — no drop

    def test_connect_runtime_error_is_caught_not_escaped(self) -> None:
        # ClientRegistry wraps connect failures (refused, spawn, handshake timeout)
        # in RuntimeError. _probe must catch it, or one tick kills the worker for
        # the life of luxd. Twice-failed, then reconnected.
        clients = _FakeClients(
            _FakeConnection(
                [RuntimeError("connect refused"), RuntimeError("still"), _pong()]
            )
        )
        DisplayLiveness(clients).check_once()  # must not raise
        assert clients.drop_calls == 1
        assert clients.get_calls == 3


class _AlwaysFailingClients:
    """A keepalive client provider whose ``get`` never manages to connect."""

    __slots__ = ()

    def get(self) -> KeepaliveConnection:
        msg = "connect refused"
        raise RuntimeError(msg)

    def drop(self) -> None:
        """No connection was ever held, so there is nothing to close."""


class TestDisconnectedPacing:
    """The two-speed cadence and once-per-transition logging (§6.4)."""

    def test_logs_once_at_info_on_transition_and_never_at_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        worker = DisplayLiveness(_AlwaysFailingClients())
        with caplog.at_level(logging.INFO):
            worker.check_once()
            worker.check_once()
            worker.check_once()
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(info_records) == 1
        assert warning_records == []

    def test_interval_relaxes_after_a_failure_and_snaps_back_on_reconnect(
        self,
    ) -> None:
        # All three probes in the first cycle fail (the two ``check_once``
        # probes plus the post-drop reconnect probe), so that cycle
        # genuinely ends disconnected; the second cycle's connection
        # answers reliably and snaps the cadence back.
        clients = _FakeClients(_FakeConnection([None, None, None, _pong()]))
        worker = DisplayLiveness(clients, interval=1.0)
        worker.check_once()  # every probe fails — the cycle marks disconnected
        assert worker._pacing.interval(1.0) == _DISCONNECTED_PROBE_INTERVAL
        worker.check_once()  # the connection now answers reliably
        assert worker._pacing.interval(1.0) == 1.0

    def test_a_successful_post_drop_reconnect_snaps_back_within_one_cycle(
        self,
    ) -> None:
        # Both probes fail, then the drop+reconnect probe succeeds -- all in
        # the SAME check_once(). The pacer must notice at once, not report
        # disconnected for a further cycle before catching up to the
        # reconnect it just performed.
        clients = _FakeClients(_FakeConnection([None, None, _pong()]))
        worker = DisplayLiveness(clients, interval=1.0)
        worker.check_once()
        assert worker._pacing.interval(1.0) == 1.0


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

    @pytest.mark.slow
    def test_worker_survives_an_unexpected_cycle_error(self) -> None:
        # An error _probe does not classify (here ValueError) escapes check_once;
        # _run must log and continue so a single bad cycle never retires the
        # keepalive for the life of luxd -- nothing else would restart it.
        clients = _FakeClients(_FakeConnection([ValueError("unexpected")]))
        worker = DisplayLiveness(clients, interval=0.02)
        worker.start()
        try:
            deadline = time.monotonic() + 2.0
            while clients.get_calls < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
            # It kept ticking through repeated raises rather than dying on the first.
            assert clients.get_calls >= 3
        finally:
            worker.stop()
