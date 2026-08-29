"""Unit tests for punt_lux.display.pending_interactions — the interaction buffer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.display.pending_interactions import PendingInteractions
from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from collections.abc import Sequence


def _event(
    element_id: str, *, kind: str = "clicked", scene_id: str | None = None
) -> RemoteEventHandlerInvocation:
    """Build a minimal interaction for the buffer tests."""
    return RemoteEventHandlerInvocation(
        element_id=element_id,
        action="click",
        event_kind=kind,
        ts=1.0,
        scene_id=scene_id,
    )


def _ids(events: Sequence[RemoteEventHandlerInvocation]) -> list[str]:
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
        assert _ids(evicted.lost) == ["stale"]
        assert _ids(evicted.compensable) == ["stale"]  # nothing newer holds it
        assert _ids(buf.pending_events()) == ["fresh"]

    def test_expire_evicts_overflow_oldest_first(self) -> None:
        buf = PendingInteractions(max_age=100.0, max_count=2)
        buf.admit([_event("old"), _event("mid"), _event("new")], now=100.0)
        evicted = buf.expire(now=100.0)
        assert _ids(evicted.lost) == ["old"]  # oldest pushed out past the cap
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
        assert _ids(evicted.lost) == ["held"]  # aged out on its original clock
        assert buf.is_empty

    def test_an_eviction_a_still_held_gesture_supersedes_is_not_compensable(
        self,
    ) -> None:
        # Two quick toggles of one header: the first ages out while the second is
        # still held. The split is taken against the buffer as it stands, so the
        # older eviction owes nothing -- the second toggle is still speaking.
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("h", kind="header_toggled")], now=100.0)
        buf.admit([_event("h", kind="header_toggled")], now=103.5)
        evicted = buf.expire(now=104.0)  # the first is 4s old
        assert _ids(evicted.lost) == ["h"]
        assert evicted.compensable == ()
        assert _ids(buf.pending_events()) == ["h"]  # the second toggle still held

    def test_a_gesture_lost_whole_compensates_its_last_eviction_only(self) -> None:
        # Both toggles age out together: nothing is left speaking for the header,
        # so the newest eviction -- and only it -- hands the latch back.
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("h", kind="header_toggled")], now=100.0)
        buf.admit([_event("h", kind="header_toggled")], now=100.5)
        evicted = buf.expire(now=110.0)
        assert _ids(evicted.lost) == ["h", "h"]
        assert evicted.compensable == (evicted.lost[-1],)
        assert buf.is_empty


class TestBulkEviction:
    """Clear and stale-element sweeps evict held interactions for compensation."""

    def test_evict_all_returns_everything_and_empties(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("a"), _event("b")], now=100.0)
        evicted = buf.evict_all()  # the display was cleared
        assert _ids(evicted.lost) == ["a", "b"]
        assert _ids(evicted.compensable) == ["a", "b"]  # nothing survives to hold
        assert buf.is_empty

    def test_discard_elements_removes_matching_preserving_order(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("keep1"), _event("gone"), _event("keep2")], now=100.0)
        removed = buf.discard_elements({"gone"})  # element was replaced away
        assert _ids(removed.lost) == ["gone"]
        assert _ids(removed.compensable) == ["gone"]  # the element took all of them
        assert _ids(buf.pending_events()) == ["keep1", "keep2"]  # order preserved


class TestDiscardScenes:
    """Scene-scoped discard, in isolation from the render-loop/scene-replica
    integration coverage of the same operation (``test_display_partition.py``'s
    ``test_close_frame_leaves_a_shared_id_alone_in_a_frame_still_up`` and
    ``test_close_frame_leaves_a_menu_click_alone``, and
    ``test_scene_replica.py``'s ``test_closing_names_no_scene_of_a_frame_that_stays_up``
    already pin the shared-element-id scenario end to end)."""

    def test_discard_scenes_with_empty_set_is_a_noop(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("a", scene_id="s1"), _event("b", scene_id="s2")], now=100.0)
        removed = buf.discard_scenes(set())
        assert removed.lost == ()
        assert _ids(buf.pending_events()) == ["a", "b"]

    def test_discard_scenes_matching_no_held_scene_is_a_noop(self) -> None:
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("a", scene_id="s1"), _event("b", scene_id="s2")], now=100.0)
        removed = buf.discard_scenes({"no-such-scene"})
        assert removed.lost == ()
        assert _ids(buf.pending_events()) == ["a", "b"]

    def test_discard_scenes_preserves_survivor_order(self) -> None:
        # Removing a scene from the middle of the buffer must not disturb the
        # relative order of what is left holding.
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit(
            [
                _event("keep1", scene_id="s1"),
                _event("gone", scene_id="s2"),
                _event("keep2", scene_id="s1"),
            ],
            now=100.0,
        )
        removed = buf.discard_scenes({"s2"})
        assert _ids(removed.lost) == ["gone"]
        assert removed.lost[0].scene_id == "s2"
        assert _ids(removed.compensable) == ["gone"]  # the scene took all of them
        assert _ids(buf.pending_events()) == ["keep1", "keep2"]  # order preserved

    def test_discard_scenes_leaves_a_broadcast_event_alone(self) -> None:
        # A menu-bar click carries no scene_id -- explicitly set here, since a
        # bare RemoteEventHandlerInvocation defaults to None regardless -- so it
        # belongs to no frame and must survive discard_scenes no matter which
        # scenes are named. Production stamps scene_id in _emit_event; here it
        # is set by hand so the assertion is pinned rather than accidental.
        buf = PendingInteractions(max_age=3.0, max_count=128)
        buf.admit([_event("menu-item", scene_id=None)], now=100.0)
        removed = buf.discard_scenes({"s1", "s2"})
        assert removed.lost == ()
        assert _ids(buf.pending_events()) == ["menu-item"]
        assert buf.pending_events()[0].scene_id is None
