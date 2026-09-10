"""DisconnectedRetry — the paced, logged wait HubReplicator's disconnected
branch delegates to (display-presence-demand-driven.md §6.2, §6.3, §6.5)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.backoff_config import BackoffConfig
from punt_lux.domain.hub.disconnected_retry import DisconnectedRetry

if TYPE_CHECKING:
    import pytest

    from punt_lux.domain.hub.reconnect_wait import ReconnectWait


class _FakeClients:
    """Records every ``wait_for_reconnect`` call; never actually blocks."""

    waits: list[float]
    since_gens: list[int]
    __slots__ = ("since_gens", "waits")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.waits = []
        self.since_gens = []
        return self

    @property
    def reconnect_generation(self) -> int:
        return 0

    def wait_for_reconnect(self, wait: ReconnectWait) -> bool:
        self.waits.append(wait.timeout)
        self.since_gens.append(wait.since_gen)
        return False


def test_wait_climbs_from_base_to_cap() -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    for _ in range(7):
        retry.wait(clients, since_gen=0)
    assert clients.waits == [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 120.0]
    assert retry.current_delay == 120.0


def test_reset_returns_the_delay_to_base() -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    retry.wait(clients, since_gen=0)
    retry.wait(clients, since_gen=0)
    assert retry.current_delay == 8.0

    retry.reset()

    assert retry.current_delay == 2.0
    retry.wait(clients, since_gen=0)
    assert clients.waits[-1] == 2.0  # the climb restarts from base


def test_wait_calls_clients_wait_for_reconnect_with_the_current_delay() -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    retry.wait(clients, since_gen=0)
    assert clients.waits == [2.0]


def test_wait_forwards_the_callers_gen_snapshot_unchanged() -> None:
    # DisconnectedRetry never reinterprets since_gen -- it is purely the
    # caller's (the replicator's) snapshot, taken before its own dial
    # attempt, threaded straight through to wait_for_reconnect.
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    retry.wait(clients, since_gen=42)
    assert clients.since_gens == [42]


def test_logs_once_at_info_on_transition_then_debug_on_repeats(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    logger_name = "punt_lux.domain.hub.disconnected_retry"
    with caplog.at_level(logging.DEBUG, logger=logger_name):
        retry.wait(clients, since_gen=0)
        retry.wait(clients, since_gen=0)
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(info_records) == 1
    assert len(debug_records) == 1
