"""SearchFocusArbiter — the autofocus arm/consume decision, pure logic.

No live frame is needed: the focus-once and refocus-after-commit decision is a
pure function over two per-scene WidgetState slots, pinned here. The actual
set_keyboard_focus_here call and the feel are the operator's visual check.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.search_focus_arbiter import SearchFocusArbiter
from punt_lux.scene.widget_state import WidgetState


def _arbiter() -> tuple[SearchFocusArbiter, WidgetState]:
    ws = WidgetState()
    return SearchFocusArbiter(ws, "table-search"), ws


def test_focuses_once_on_the_scenes_first_frame() -> None:
    arbiter, _ = _arbiter()
    assert arbiter.should_focus()  # first arrival — grab focus
    arbiter.record_focused()
    assert not arbiter.should_focus()  # already focused, nothing armed


def test_refocus_after_an_enter_commit() -> None:
    arbiter, _ = _arbiter()
    arbiter.record_focused()  # scene focused once
    assert not arbiter.should_focus()
    arbiter.arm_refocus()  # the input enter-committed
    assert arbiter.should_focus()  # return focus next frame
    arbiter.record_focused()  # consumed
    assert not arbiter.should_focus()  # disarmed again


def test_focus_is_not_re_stolen_on_a_later_frame_or_re_push() -> None:
    # The slots are durable, so a fresh arbiter over the same scene state (the next
    # frame, or a poller re-push) does not steal focus a second time.
    arbiter, ws = _arbiter()
    arbiter.record_focused()
    later = SearchFocusArbiter(ws, "table-search")
    assert not later.should_focus()


def test_a_non_bool_in_either_slot_is_not_a_flag() -> None:
    # Both slots live in an untyped per-scene store, and only a flag this
    # arbiter wrote counts. A value of another type must neither suppress the
    # first focus (a truthy "seen" the arbiter never recorded) nor arm a
    # refocus the input never committed.
    arbiter, ws = _arbiter()
    ws.set(f"table-search{WidgetState.FOCUS_SEEN_SUFFIX}", "yes")
    assert arbiter.should_focus()

    arbiter.record_focused()
    ws.set(f"table-search{WidgetState.FOCUS_REFOCUS_SUFFIX}", "armed")
    assert not arbiter.should_focus()


def test_discard_for_re_arms_focus_for_a_re_added_input() -> None:
    # A torn-down then re-added scene (discard_for on removal) focuses again on
    # its fresh arrival.
    arbiter, ws = _arbiter()
    arbiter.record_focused()
    ws.discard_for("table-search")
    reborn = SearchFocusArbiter(ws, "table-search")
    assert reborn.should_focus()
