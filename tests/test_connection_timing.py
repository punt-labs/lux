"""Unit tests for punt_lux.connection_timing — the tied recovery-timing invariant."""

from __future__ import annotations

from punt_lux.connection_timing import CONNECTION_TIMING, ConnectionTiming


class TestConnectionTiming:
    """The buffer bound is derived from the keepalive cadence and always covers it."""

    def test_reconnect_worst_case_is_interval_plus_two_pings(self) -> None:
        timing = ConnectionTiming(keepalive_interval=2.0, ping_timeout=1.0)
        assert timing.reconnect_worst_case == 2.0 + 2 * 1.0

    def test_interaction_max_age_covers_the_reconnect_worst_case(self) -> None:
        # The invariant: the buffer must outlive the worst-case reconnect.
        assert (
            CONNECTION_TIMING.interaction_max_age
            >= CONNECTION_TIMING.reconnect_worst_case
        )

    def test_tuning_the_cadence_grows_the_buffer_bound(self) -> None:
        # A slower keepalive must widen the hold, not silently leave it behind.
        slow = ConnectionTiming(keepalive_interval=5.0)
        fast = ConnectionTiming(keepalive_interval=2.0)
        assert slow.interaction_max_age > fast.interaction_max_age
        assert slow.interaction_max_age >= slow.reconnect_worst_case
