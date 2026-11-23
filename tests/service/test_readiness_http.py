"""A watchdog and individual socket operations spend one absolute budget."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.service._readiness_http import ProbeDeadline


def test_remaining_time_decreases_and_expires_without_renewal() -> None:
    with patch("punt_lux.service._readiness_http.time.monotonic") as clock:
        clock.return_value = 10
        budget = ProbeDeadline(5)
        assert budget.remaining() == 5
        clock.return_value = 13
        assert budget.remaining() == 2
        clock.return_value = 15
        with pytest.raises(TimeoutError, match="deadline elapsed"):
            budget.remaining()


@pytest.mark.parametrize("seconds", [0, -1])
def test_nonpositive_budget_cannot_start_work(seconds: int) -> None:
    with (
        patch("punt_lux.service._readiness_http.time.monotonic", return_value=10),
        pytest.raises(TimeoutError),
    ):
        ProbeDeadline(seconds).remaining()


def test_missing_socket_cannot_start_a_watchdog() -> None:
    with (
        pytest.raises(ConnectionError, match="no socket"),
        ProbeDeadline(1).watch(None),
    ):
        pytest.fail("missing socket was accepted")
