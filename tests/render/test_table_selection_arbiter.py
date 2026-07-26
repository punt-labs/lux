"""TableSelectionArbiter — the row-selection bridge across the re-push window.

The fragile part of the table's selection is what the display seeds its storage
from between a user gesture and the Hub's confirming re-push. These prove it at
the pure-function level (no live ImGui frame), the analogue of the tab-bar
arbiter's tests: the pending set is held so accumulated picks survive, and the
Hub value wins once it moves.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.table_row_arbiter import TableSelectionArbiter
from punt_lux.scene.widget_state import WidgetState


def _arbiter() -> tuple[TableSelectionArbiter, WidgetState]:
    ws = WidgetState()
    return TableSelectionArbiter(ws, "grid"), ws


def test_no_pending_returns_the_authoritative_set() -> None:
    arbiter, _ = _arbiter()
    assert arbiter.effective_selection(frozenset({"a"})) == frozenset({"a"})


def test_second_gesture_accumulates_instead_of_dropping_the_first() -> None:
    # THE CENTERPIECE — the A-dropped bug. Ctrl-click A fires {A}; before the
    # re-push lands the authoritative value is still {}. A naive renderer would
    # reseed from {} and a ctrl-click B would fire {B}, silently losing A. The
    # arbiter holds {A} pending, so the second frame seeds from {A} and the B
    # click accumulates to {A, B}.
    arbiter, _ = _arbiter()

    # Frame 1 — click A. Nothing pending, so the display seeds from the empty Hub
    # value; the gesture fires {A}, which the renderer records as pending.
    assert arbiter.effective_selection(frozenset()) == frozenset()
    arbiter.note_pending(frozenset({"a"}))
    arbiter.record_honoured(frozenset())

    # Frame 2 — click B, no re-push yet (Hub still {}). The seed keeps A.
    seed = arbiter.effective_selection(frozenset())
    assert seed == frozenset({"a"}), "the first pick must survive into frame 2"
    arbiter.note_pending(frozenset({"a", "b"}))
    arbiter.record_honoured(frozenset())

    # Frame 3 — still no re-push. Both picks are held.
    assert arbiter.effective_selection(frozenset()) == frozenset({"a", "b"})


def test_hub_catch_up_clears_the_pending() -> None:
    # When the Hub's confirming re-push lands (authoritative reaches the pending),
    # the pending is dropped and the authoritative value is honoured — no flicker,
    # and no stale hold once the Hub agrees.
    arbiter, _ = _arbiter()
    arbiter.note_pending(frozenset({"a"}))
    arbiter.record_honoured(frozenset())

    assert arbiter.effective_selection(frozenset({"a"})) == frozenset({"a"})
    arbiter.record_honoured(frozenset({"a"}))
    # Pending was cleared: a later frame with no gesture stays on the Hub value.
    assert arbiter.effective_selection(frozenset({"a"})) == frozenset({"a"})


def test_unrelated_hub_push_wins_over_a_stale_pending() -> None:
    # An external selection push (e.g. an agent apply_patch) that never equals the
    # pending must still win — otherwise the display would ignore the Hub forever.
    arbiter, _ = _arbiter()
    arbiter.note_pending(frozenset({"a"}))
    arbiter.record_honoured(frozenset())

    assert arbiter.effective_selection(frozenset({"x"})) == frozenset({"x"})
    # The pending was dropped: the next frame follows the Hub, not {a}.
    arbiter.record_honoured(frozenset({"x"}))
    assert arbiter.effective_selection(frozenset({"x"})) == frozenset({"x"})


def test_discard_for_clears_the_bridge_for_a_re_added_table() -> None:
    # A removed-then-re-added table must honour its fresh selection, not an earlier
    # pending set left in the per-scene state.
    arbiter, ws = _arbiter()
    arbiter.note_pending(frozenset({"a"}))
    arbiter.record_honoured(frozenset())

    ws.discard_for("grid")

    assert arbiter.effective_selection(frozenset({"z"})) == frozenset({"z"})
