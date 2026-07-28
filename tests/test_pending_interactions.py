"""Unit tests for punt_lux.display.pending_interactions — the interaction buffer."""

from __future__ import annotations

from punt_lux.display.pending_interactions import PendingInteractions
from punt_lux.protocol import RemoteEventHandlerInvocation


def _event(element_id: str, *, kind: str = "clicked") -> RemoteEventHandlerInvocation:
    """Build a minimal interaction for the buffer tests."""
    return RemoteEventHandlerInvocation(
        element_id=element_id, action="click", event_kind=kind, ts=1.0
    )


def _ids(events: list[RemoteEventHandlerInvocation]) -> list[str]:
    return [ev.element_id for ev in events]


class TestAdmitAndDeliver:
    """Admitted interactions are readable in order and dropped by prefix."""

    def test_admit_then_pending_events_preserves_order(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        assert buf.pending_events() == []  # empty before anything is admitted
        buf.admit([_event("a"), _event("b")], now=100.0)
        assert not buf.is_empty
        assert _ids(buf.pending_events()) == ["a", "b"]

    def test_discard_prefix_drops_the_delivered_front(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("a"), _event("b"), _event("c")], now=100.0)
        buf.discard_prefix(2)  # a and b delivered
        assert _ids(buf.pending_events()) == ["c"]

    def test_reconnect_delivers_the_whole_gap_in_order(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        # Clicks land across a no-client gap, each admitted on its own frame.
        buf.admit([_event("c1")], now=100.0)
        buf.admit([_event("c2")], now=100.5)
        buf.admit([_event("c3")], now=101.0)
        events = buf.pending_events()
        assert _ids(events) == ["c1", "c2", "c3"]
        buf.discard_prefix(len(events))  # a reconnect delivers them all
        assert buf.is_empty


class TestExpire:
    """Aged or overflowed interactions are returned for compensation."""

    def test_expire_evicts_aged_leaving_fresh(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("stale")], now=100.0)
        buf.admit([_event("fresh")], now=104.0)
        evicted = buf.expire(now=104.0)  # stale is 4s old, past the 3s bound
        assert _ids(evicted) == ["stale"]
        assert _ids(buf.pending_events()) == ["fresh"]

    def test_expire_evicts_overflow_oldest_first(self) -> None:
        buf = PendingInteractions(max_age=100.0, max_count=2)
        buf.admit([_event("old"), _event("mid"), _event("new")], now=100.0)
        evicted = buf.expire(now=100.0)
        assert _ids(evicted) == ["old"]  # oldest pushed out past the cap
        assert _ids(buf.pending_events()) == ["mid", "new"]

    def test_age_survives_a_discard_so_a_stalled_frame_still_expires(self) -> None:
        # A held event keeps its original age across a prefix discard, so a later
        # frame -- even one stalled long past the bound -- still expires it and
        # does not carry it forever.
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("delivered"), _event("held")], now=100.0)
        buf.discard_prefix(1)  # "delivered" landed; "held" kept its held_at=100
        assert _ids(buf.pending_events()) == ["held"]
        evicted = buf.expire(now=110.0)  # the stalled next frame arrives 10s later
        assert _ids(evicted) == ["held"]  # aged out on its original clock, not reset
        assert buf.is_empty


class TestBulkEviction:
    """Clear and stale-element sweeps evict held interactions for compensation."""

    def test_evict_all_returns_everything_and_empties(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("a"), _event("b")], now=100.0)
        evicted = buf.evict_all()  # the display was cleared
        assert _ids(evicted) == ["a", "b"]
        assert buf.is_empty

    def test_discard_elements_removes_matching_preserving_order(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("keep1"), _event("gone"), _event("keep2")], now=100.0)
        removed = buf.discard_elements({"gone"})  # element was replaced away
        assert _ids(removed) == ["gone"]
        assert _ids(buf.pending_events()) == ["keep1", "keep2"]  # order preserved
