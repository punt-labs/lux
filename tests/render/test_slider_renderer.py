"""SliderRenderer + SliderArbiter under the commit-echo rule.

The pure ``SliderArbiter`` honour-or-defer decision is tested here without
imgui; the renderer paint-seam tests (which drive a scripted fake imgui) live
alongside it once the renderer lands. The slider carries a ``float`` in
``[min, max]`` where ``input_text`` carries a ``str``; the reconciliation logic
is identical, so the invariants mirror the input_text suite, each fidelity-
checked against the naive implementation it must beat.

Float-specific cases the string suite cannot have:

- EXACT-EQUALITY — commit a full-precision drag float (``0.1 + 0.2``), echo the
  same float, assert the window closes; a bit-distinct neighbour is honoured
  immediately. This is the executable form of the value-equality argument.
- SIGNED-ZERO — ``-0.0`` and ``0.0`` compare equal, so a commit at ``-0.0``
  whose echo returns ``0.0`` still closes its window.
"""

from __future__ import annotations

from typing import Self

from punt_lux.display.renderers.imgui.slider_selection import SliderArbiter
from punt_lux.scene.widget_state import WidgetState

# -- the arbiter: the pure honour-or-defer decision ------------------------


class TestArbiterResolve:
    def test_idle_resolves_to_the_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: a fresh (idle) thumb renders the Hub value.
        arb = SliderArbiter(WidgetState(), "s")
        assert arb.resolve(42.0) == 42.0

    def test_idle_tracks_the_latest_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: each idle frame honours the current Hub value, so an
        # agent-driven change is picked up without any per-field bookkeeping.
        arb = SliderArbiter(WidgetState(), "s")
        assert arb.resolve(42.0) == 42.0
        assert arb.resolve(63.5) == 63.5

    def test_dragging_defers_to_the_local_buffer(self) -> None:
        # NO-CLOBBER: once a frame has observed a real drag, a Hub-driven value
        # is ignored — the in-progress thumb wins.
        arb = SliderArbiter(WidgetState(), "s")
        arb.observe(edited=True, value=30.0)
        assert arb.resolve(99.0) == 30.0
        assert arb.resolve(99.0) == 30.0

    def test_grab_without_drag_keeps_honouring(self) -> None:
        # HONOUR-DISCIPLINE: an active frame with no real drag does not begin
        # deferring — the thumb still honours the Hub, so an echo can reach it.
        arb = SliderArbiter(WidgetState(), "s")
        arb.observe(edited=False, value=42.0)
        assert arb.resolve(63.5) == 63.5

    def test_release_returns_to_honouring_the_hub(self) -> None:
        arb = SliderArbiter(WidgetState(), "s")
        arb.observe(edited=True, value=30.0)
        arb.release()
        assert arb.resolve(70.0) == 70.0

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        SliderArbiter(ws, "a").observe(edited=True, value=10.0)
        assert SliderArbiter(ws, "a").resolve(1.0) == 10.0
        assert SliderArbiter(ws, "b").resolve(2.0) == 2.0


class TestArbiterCommitEcho:
    def test_commit_is_honoured_until_the_hub_value_moves(self) -> None:
        # REFOCUS-DURABILITY at the arbiter: after commit, an idle frame whose
        # Hub value is still the pre-echo value renders the committed value —
        # the optimistic echo — not the stale Hub value.
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(80.0, hub_value=50.0)  # committed 80; Hub still 50
        assert arb.resolve(50.0) == 80.0  # pre-echo window: honour committed
        assert arb.resolve(50.0) == 80.0  # still pending

    def test_commit_record_clears_once_the_echo_arrives(self) -> None:
        # Once the Hub value moves off the commit-time value (the echo, or an
        # agent override), the record clears and the thumb honours the Hub.
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(80.0, hub_value=50.0)
        assert arb.resolve(80.0) == 80.0  # echo landed: Hub == committed
        assert arb.resolve(25.0) == 25.0  # record gone: honour the Hub

    def test_dragging_wins_over_a_pending_commit(self) -> None:
        # A live drag still beats the commit-echo record: the buffer is
        # authoritative while dragging, whatever the pending committed value.
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(80.0, hub_value=50.0)
        arb.observe(edited=True, value=33.0)
        assert arb.resolve(50.0) == 33.0

    def test_agent_override_mid_window_drops_the_committed_value(self) -> None:
        # AGENT-OVERRIDE-MID-WINDOW: the commit-hub marker is load-bearing.
        # resolve honours the committed value only while the Hub still holds the
        # value observed AT COMMIT TIME; it does not key off "hub != committed".
        # Commit 80 while the Hub holds a DISTINCT pre-echo 20 (not the default):
        # the window honours 80 while the Hub reads 20, but an agent override
        # that drives the Hub to a THIRD value drops the committed value and
        # honours the Hub. A wrong impl comparing hub against committed would
        # keep returning 80 here (the override differs from committed too).
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(80.0, hub_value=20.0)
        assert arb.resolve(20.0) == 80.0  # window open, Hub still pre-echo 20
        assert arb.resolve(55.0) == 55.0  # override to a third value: honour Hub

    def test_commit_value_equal_to_current_hub_persists_then_clears(self) -> None:
        # BOUNDARY commit(x, hub_value=x): committed and commit-hub coincide. The
        # record is still live and honoured while the Hub reads x, and clears on
        # the first Hub move. The output x is identical whether the record is
        # present or forgotten, so the slot is read directly to prove it
        # persisted through the equal-value frames and that _forget_commit fired
        # exactly on the move.
        ws = WidgetState()
        arb = SliderArbiter(ws, "s")
        committed_key = f"s{WidgetState.SLIDER_COMMITTED_SUFFIX}"
        arb.commit(50.0, hub_value=50.0)
        assert arb.resolve(50.0) == 50.0  # committed == Hub: honour, record live
        assert ws.get(committed_key) == 50.0  # record persists
        assert arb.resolve(50.0) == 50.0  # still live, still honoured
        assert ws.get(committed_key) == 50.0
        assert arb.resolve(70.0) == 70.0  # Hub moved off: honour the Hub
        assert ws.get(committed_key) is None  # _forget_commit fired on the move


class TestArbiterFloatEquality:
    def test_full_precision_commit_echo_closes_the_window(self) -> None:
        # EXACT-EQUALITY: a drag lands on 0.1 + 0.2 (not 0.3 in IEEE-754); the
        # echo returns the SAME bits, so hub == commit-time-hub holds exactly
        # and the window closes. No epsilon, no rounding.
        drift = 0.1 + 0.2  # 0.30000000000000004
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(drift, hub_value=0.0)
        assert arb.resolve(0.0) == drift  # window open: honour committed
        assert arb.resolve(drift) == drift  # echo landed bit-for-bit: converge
        assert arb.resolve(0.5) == 0.5  # record cleared: honour the Hub

    def test_bit_distinct_neighbour_is_honoured_immediately(self) -> None:
        # A neighbour one ULP away from the commit-time Hub value is a genuine
        # agent override, honoured at once — an epsilon compare would mask it.
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(80.0, hub_value=0.3)
        neighbour = 0.30000000000000004  # 0.1 + 0.2, distinct from 0.3
        assert arb.resolve(neighbour) == neighbour

    def test_signed_zero_echo_closes_the_window(self) -> None:
        # -0.0 == 0.0 in IEEE-754, so a commit at -0.0 whose echo returns 0.0
        # still recognises the echo and closes the window.
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(-0.0, hub_value=-0.0)
        assert arb.resolve(0.0) == -0.0  # echo (0.0) == commit-hub (-0.0)
        assert arb.resolve(5.0) == 5.0  # record cleared


# -- fidelity: the naive implementations each invariant must beat ----------


class _HonourEveryFrameArbiter:
    """Naive: render the Hub value every frame, ignoring that the user drags."""

    def resolve(self, hub_value: float) -> float:
        return hub_value

    def observe(self, *, edited: bool, value: float) -> None:
        _ = (edited, value)

    def release(self) -> None:
        return None


class _SeedOnceArbiter:
    """Naive: seed the buffer once; a later idle Hub drive is lost."""

    _state: WidgetState
    _key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._key = element_id
        return self

    def resolve(self, hub_value: float) -> float:
        if self._state.get(self._key) is None:
            self._state.set(self._key, hub_value)
        return self._state.get_float(self._key, default=hub_value)


class TestArbiterFidelity:
    def test_honour_every_frame_clobbers_the_live_thumb(self) -> None:
        # NO-CLOBBER fidelity: the honour-every-frame naive lets a stale Hub
        # value overwrite the buffer mid-drag; the real arbiter defers.
        naive = _HonourEveryFrameArbiter()
        naive.observe(edited=True, value=30.0)
        assert naive.resolve(99.0) == 99.0  # clobbered — the bug

        real = SliderArbiter(WidgetState(), "s")
        real.observe(edited=True, value=30.0)
        assert real.resolve(99.0) == 30.0  # deferred — the fix

    def test_seed_once_ignores_a_later_idle_hub_drive(self) -> None:
        # HONOUR-WHEN-IDLE fidelity: the seed-once naive keeps the first value;
        # the real arbiter re-honours the current Hub value every idle frame.
        naive = _SeedOnceArbiter(WidgetState(), "s")
        assert naive.resolve(42.0) == 42.0
        assert naive.resolve(63.5) == 42.0  # stale — the bug

        real = SliderArbiter(WidgetState(), "s")
        assert real.resolve(42.0) == 42.0
        assert real.resolve(63.5) == 63.5  # honoured — the fix


class TestRemovalMidDrag:
    def test_removal_mid_drag_drops_the_buffer(self) -> None:
        # A slider removed mid-drag drops its in-progress value via discard_for;
        # a re-added same-id slider honours its fresh Hub value.
        ws = WidgetState()
        arb = SliderArbiter(ws, "s")
        arb.observe(edited=True, value=30.0)
        assert arb.resolve(99.0) == 30.0  # the buffer wins while dragging

        ws.discard_for("s")  # the element is removed mid-drag

        assert SliderArbiter(ws, "s").resolve(70.0) == 70.0

    def test_removal_clears_a_pending_commit_echo(self) -> None:
        ws = WidgetState()
        arb = SliderArbiter(ws, "s")
        arb.commit(80.0, hub_value=50.0)
        assert arb.resolve(50.0) == 80.0  # pending: honour the committed value

        ws.discard_for("s")  # removed while the echo is pending

        assert SliderArbiter(ws, "s").resolve(70.0) == 70.0
