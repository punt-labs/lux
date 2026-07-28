"""Unit tests for punt_lux.display.pending_interactions — the interaction buffer."""

from __future__ import annotations

from punt_lux.display.pending_interactions import PendingInteractions
from punt_lux.protocol import RemoteEventHandlerInvocation


def _event(element_id: str, *, kind: str = "clicked") -> RemoteEventHandlerInvocation:
    """Build a minimal interaction for the buffer tests."""
    return RemoteEventHandlerInvocation(
        element_id=element_id, action="click", event_kind=kind, ts=1.0
    )


class TestHoldAndDrain:
    """Interactions held during a dropout deliver on reconnect, in order."""

    def test_hold_keeps_within_bound(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        evicted = buf.hold([_event("a"), _event("b")], now=100.0)
        assert evicted == []  # nothing past the bound yet
        assert not buf.is_empty

    def test_drain_delivers_held_before_new_in_order(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.hold([_event("held1"), _event("held2")], now=100.0)
        batch = buf.drain_to([_event("new1")])
        assert [ev.element_id for ev in batch] == ["held1", "held2", "new1"]
        assert buf.is_empty  # drain empties the buffer

    def test_reconnect_after_gap_delivers_the_gap_clicks(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        # Three clicks land across a no-client gap, each a separate flush.
        buf.hold([_event("c1")], now=100.0)
        buf.hold([_event("c2")], now=100.5)
        buf.hold([_event("c3")], now=101.0)
        # A client returns within the bound: every gap click is delivered, in order.
        batch = buf.drain_to([])
        assert [ev.element_id for ev in batch] == ["c1", "c2", "c3"]


class TestEviction:
    """Interactions past the bound are returned for compensation, not delivered."""

    def test_aged_past_bound_is_evicted(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.hold([_event("stale")], now=100.0)
        # A later flush past max_age evicts the stale click for compensation.
        evicted = buf.hold([_event("fresh")], now=104.0)
        assert [ev.element_id for ev in evicted] == ["stale"]
        # The fresh click, still within the bound, stays held.
        assert not buf.is_empty
        assert [ev.element_id for ev in buf.drain_to([])] == ["fresh"]

    def test_overflow_evicts_oldest_first(self) -> None:
        buf = PendingInteractions(max_age=100.0, max_count=2)
        evicted = buf.hold([_event("old"), _event("mid"), _event("new")], now=100.0)
        assert [ev.element_id for ev in evicted] == ["old"]  # oldest pushed out
        assert [ev.element_id for ev in buf.drain_to([])] == ["mid", "new"]
