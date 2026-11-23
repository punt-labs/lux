"""The shared display round-trip budget retains its established value."""

from __future__ import annotations

from punt_lux.kernel.display_defaults import DEFAULT_RECV_TIMEOUT


def test_display_round_trip_budget_is_five_seconds() -> None:
    assert DEFAULT_RECV_TIMEOUT == 5.0
