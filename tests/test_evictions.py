"""Unit tests for punt_lux.display.evictions — what a lost interaction still owes.

An eviction owes the display its optimism back only when nothing newer is
speaking for the element. These cover the split itself; the widget-state effect
of honouring it is in ``test_interaction_delivery``.
"""

from __future__ import annotations

from punt_lux.display.evictions import Evictions
from punt_lux.protocol import RemoteEventHandlerInvocation


def _event(
    element_id: str,
    *,
    kind: str = "header_toggled",
    scene_id: str | None = "s1",
    value: object = None,
) -> RemoteEventHandlerInvocation:
    """Build one interaction as the pending buffer held it."""
    return RemoteEventHandlerInvocation(
        element_id=element_id,
        action="changed",
        event_kind=kind,
        scene_id=scene_id,
        ts=1.0,
        value=value,
    )


def _values(events: tuple[RemoteEventHandlerInvocation, ...]) -> list[object]:
    return [ev.value for ev in events]


class TestSupersession:
    """An eviction a newer outstanding gesture speaks for compensates nothing."""

    def test_older_eviction_is_not_compensable_while_a_newer_one_is_held(self) -> None:
        older = _event("h", value=True)
        newer = _event("h", value=False)

        evicted = Evictions.of([older], [newer])

        assert evicted.lost == (older,)
        assert evicted.compensable == ()

    def test_the_only_eviction_is_compensable(self) -> None:
        lost = _event("h", value=True)

        evicted = Evictions.of([lost], [])

        assert evicted.compensable == (lost,)

    def test_an_outstanding_gesture_of_another_kind_does_not_supersede(self) -> None:
        # Kinds latch different slots, so a pending tab switch says nothing about
        # a lost header toggle: the header still owes its optimism back.
        lost = _event("x", kind="header_toggled")

        evicted = Evictions.of([lost], [_event("x", kind="tab_changed")])

        assert evicted.compensable == (lost,)

    def test_an_outstanding_gesture_on_another_element_does_not_supersede(
        self,
    ) -> None:
        lost = _event("h1")

        evicted = Evictions.of([lost], [_event("h2")])

        assert evicted.compensable == (lost,)

    def test_the_same_element_in_another_scene_does_not_supersede(self) -> None:
        # The latch a compensation clears is per-scene widget state, so an id
        # repeated across scenes names two different widgets.
        lost = _event("h", scene_id="s1")

        evicted = Evictions.of([lost], [_event("h", scene_id="s2")])

        assert evicted.compensable == (lost,)


class TestWithinOneBatch:
    """A batch that loses a whole gesture compensates its last eviction once."""

    def test_only_the_last_of_a_gesture_is_compensable(self) -> None:
        first, second, third = (_event("h", value=v) for v in (True, False, True))

        evicted = Evictions.of([first, second, third], [])

        assert _values(evicted.lost) == [True, False, True]
        assert evicted.compensable == (third,)

    def test_distinct_gestures_each_compensate_in_held_order(self) -> None:
        header = _event("h", kind="header_toggled")
        tab = _event("t", kind="tab_changed")
        header_again = _event("h", kind="header_toggled")

        evicted = Evictions.of([header, tab, header_again], [])

        assert evicted.compensable == (tab, header_again)  # held order preserved

    def test_nothing_lost_compensates_nothing(self) -> None:
        evicted = Evictions.of([], [_event("h")])

        assert evicted.lost == ()
        assert evicted.compensable == ()
