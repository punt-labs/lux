"""DisconnectedRetry — the paced, logged wait HubReplicator's disconnected
branch delegates to (display-presence-demand-driven.md §6.2, §6.3, §6.5)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.backoff_config import BackoffConfig
from punt_lux.domain.hub.disconnected_retry import DisconnectedRetry

if TYPE_CHECKING:
    import pytest


class _FakeClients:
    """Records every ``wait_for_reconnect`` call; never actually blocks."""

    waits: list[float]
    __slots__ = ("waits",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.waits = []
        return self

    def wait_for_reconnect(self, timeout: float) -> bool:
        self.waits.append(timeout)
        return False


def test_wait_climbs_from_base_to_cap() -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    for _ in range(7):
        retry.wait(clients)
    assert clients.waits == [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 120.0]
    assert retry.current_delay == 120.0


def test_reset_returns_the_delay_to_base() -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    retry.wait(clients)
    retry.wait(clients)
    assert retry.current_delay == 8.0

    retry.reset()

    assert retry.current_delay == 2.0
    retry.wait(clients)
    assert clients.waits[-1] == 2.0  # the climb restarts from base


def test_wait_calls_clients_wait_for_reconnect_with_the_current_delay() -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    retry.wait(clients)
    assert clients.waits == [2.0]


def test_logs_once_at_info_on_transition_then_debug_on_repeats(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retry = DisconnectedRetry(BackoffConfig(base_delay=2.0, max_delay=120.0))
    clients = _FakeClients()
    logger_name = "punt_lux.domain.hub.disconnected_retry"
    with caplog.at_level(logging.DEBUG, logger=logger_name):
        retry.wait(clients)
        retry.wait(clients)
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(info_records) == 1
    assert len(debug_records) == 1
