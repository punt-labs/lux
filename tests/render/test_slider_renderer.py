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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import slider_renderer
from punt_lux.display.renderers.imgui.slider_selection import SliderArbiter
from punt_lux.display.renderers.slider_renderer import SliderRenderer
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest

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
        # EXACT-EQUALITY: the commit records commit-hub 0.0 with a committed
        # value of 0.1 + 0.2 (not 0.3 in IEEE-754). The echo is the Hub moving
        # to 0.1 + 0.2, which differs from the commit-time Hub 0.0 — so resolve
        # takes the FORGET branch and returns the raw Hub value, bit-for-bit
        # 0.1 + 0.2, no epsilon, no rounding. The window closes because the Hub
        # moved off commit-hub, not because committed == Hub.
        drift = 0.1 + 0.2  # 0.30000000000000004
        arb = SliderArbiter(WidgetState(), "s")
        arb.commit(drift, hub_value=0.0)
        assert arb.resolve(0.0) == drift  # window open: honour committed
        assert arb.resolve(drift) == drift  # Hub moved off commit-hub: forget
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


# -- the renderer: honour idle, defer dragging, commit once ----------------


@dataclass(frozen=True, slots=True)
class _Frame:
    """One scripted imgui frame.

    ``dragged`` is the value the user dragged to this frame — ``None`` means no
    drag, so imgui echoes the position it was handed. ``active`` and
    ``committed`` are the item-state flags queried after the widget is submitted.
    """

    dragged: float | None
    active: bool
    committed: bool


class _FakeImgui:
    """Fake imgui returning one scripted ``_Frame`` per ``slider_*`` call.

    ``recorded`` is the sequence of positions ``render`` handed to the widget —
    the honour/defer evidence (always a ``float`` for a clean cross-variant diff).
    """

    recorded: list[float]
    _frames: list[_Frame]
    _index: int
    _current: _Frame

    def __new__(cls, *frames: _Frame) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self._frames = list(frames)
        self._index = 0
        self._current = frames[0]
        return self

    def slider_float(
        self, _label: str, current: float, _v_min: float, _v_max: float, _fmt: str
    ) -> tuple[bool, float]:
        return self._advance(current)

    def slider_int(
        self, _label: str, current: int, _v_min: int, _v_max: int
    ) -> tuple[bool, int]:
        changed, value = self._advance(float(current))
        return (changed, int(value))

    def _advance(self, current: float) -> tuple[bool, float]:
        self.recorded.append(current)
        frame = self._frames[self._index]
        self._index += 1
        self._current = frame
        value = current if frame.dragged is None else frame.dragged
        return (frame.dragged is not None, value)

    def is_item_active(self) -> bool:
        return self._current.active

    def is_item_deactivated_after_edit(self) -> bool:
        return self._current.committed


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(slider_renderer, "imgui", fake)


def _slider(*, value: float = 0.0, integer: bool = False) -> SliderElement:
    return SliderElement(
        id="s", label="Vol", value=value, min=0.0, max=100.0, integer=integer
    )


class TestRendererHonour:
    def test_idle_frames_track_the_hub_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-WHEN-IDLE: two idle re-push frames with different values; the
        # position handed to imgui tracks each.
        fake = _FakeImgui(
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = SliderRenderer(WidgetState())

        renderer.render(_slider(value=42.0))
        renderer.render(_slider(value=63.5))

        assert fake.recorded == [42.0, 63.5]


class TestRendererDefer:
    def test_hub_drive_while_dragging_does_not_clobber(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-CLOBBER: the user drags to 30 (frame 1), then a Hub re-push carries
        # value=99 while the thumb is still active (frame 2). The position handed
        # to imgui stays 30, not 99.
        fake = _FakeImgui(
            _Frame(dragged=30.0, active=True, committed=False),
            _Frame(dragged=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = SliderRenderer(WidgetState())

        renderer.render(_slider(value=0.0))
        renderer.render(_slider(value=99.0))

        assert fake.recorded == [0.0, 30.0]

    def test_grab_without_drag_still_honours_a_hub_drive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-DISCIPLINE: an active frame with no drag (frame 1) does not begin
        # deferring, so a Hub re-push (frame 2) still reaches the thumb.
        fake = _FakeImgui(
            _Frame(dragged=None, active=True, committed=False),
            _Frame(dragged=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = SliderRenderer(WidgetState())

        renderer.render(_slider(value=42.0))
        renderer.render(_slider(value=63.5))

        assert fake.recorded == [42.0, 63.5]


class TestRendererCommit:
    def test_release_after_drag_fires_once_with_the_final_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # COMMIT-ON-RELEASE: drag frames fire nothing; the release frame fires
        # exactly one ValueChanged carrying the final float.
        fake = _FakeImgui(
            _Frame(dragged=75.0, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _slider(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(WidgetState())

        renderer.render(elem)
        assert fired == []  # drag frame does not fire

        renderer.render(elem)
        assert len(fired) == 1
        assert fired[0].value == 75.0
        assert fired[0].element_id == "s"

    def test_no_fire_while_merely_dragging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-FIRE-WHILE-DRAGGING: three active drag frames, no release — nothing
        # fires until the drag commits.
        fake = _FakeImgui(
            _Frame(dragged=10.0, active=True, committed=False),
            _Frame(dragged=20.0, active=True, committed=False),
            _Frame(dragged=30.0, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _slider(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)
        renderer.render(elem)

        assert fired == []


class TestRendererPostCommit:
    def test_idle_after_commit_shows_the_committed_value_until_the_echo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # POST-COMMIT LATENCY: drag -> release/commit -> idle while elem.value is
        # still the pre-echo Hub value -> the echo arrives. Through the window the
        # thumb honours the COMMITTED value, then honours the Hub once it echoes.
        fake = _FakeImgui(
            _Frame(dragged=80.0, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _slider(value=0.0)  # pre-echo Hub value
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(WidgetState())

        renderer.render(elem)  # dragging
        renderer.render(elem)  # release -> commit fires once
        renderer.render(elem)  # idle; elem.value still pre-echo 0
        renderer.render(_slider(value=80.0))  # the Hub echo landed

        assert [e.value for e in fired] == [80.0]  # exactly one commit fire
        assert fake.recorded == [0.0, 80.0, 80.0, 80.0]

    def test_agent_override_mid_window_tracks_the_hub_not_the_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # AGENT-OVERRIDE-MID-WINDOW: commit 80 while pre-echo Hub is 0; an idle
        # window frame shows committed 80, but an agent drive to a divergent third
        # value tracks the Hub, dropping the optimistic echo.
        fake = _FakeImgui(
            _Frame(dragged=80.0, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _slider(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(WidgetState())

        renderer.render(elem)  # dragging
        renderer.render(elem)  # release -> commit 80; commit-hub is 0
        renderer.render(elem)  # idle; Hub still 0 -> optimistic committed 80
        renderer.render(_slider(value=25.0))  # agent override to a third value

        assert [e.value for e in fired] == [80.0]
        assert fake.recorded == [0.0, 80.0, 80.0, 25.0]

    def test_drag_in_the_window_wins_over_the_pending_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # EDIT-IN-WINDOW-WINS: commit 80 (echo in flight), then re-grab and drag
        # to 33 while the record is live. The live thumb is authoritative.
        fake = _FakeImgui(
            _Frame(dragged=80.0, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
            _Frame(dragged=33.0, active=True, committed=False),
            _Frame(dragged=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _slider(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(WidgetState())

        renderer.render(elem)  # dragging
        renderer.render(elem)  # release -> commit 80; record live
        renderer.render(elem)  # re-grab, drag 33: buffer authoritative
        renderer.render(elem)  # still active: the live thumb wins

        assert [e.value for e in fired] == [80.0]  # only the first drag committed
        assert fake.recorded == [0.0, 80.0, 80.0, 33.0]


class TestRendererRemoval:
    def test_removal_mid_drag_drops_the_buffer_without_committing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A slider removed mid-drag drops its buffer via discard_for and never
        # reaches the release path, so no ValueChanged fires.
        fake = _FakeImgui(_Frame(dragged=30.0, active=True, committed=False))
        _install(monkeypatch, fake)
        ws = WidgetState()
        elem = _slider(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(ws)

        renderer.render(elem)  # dragging: buffer set to 30
        ws.discard_for("s")  # the element is removed mid-drag

        assert fired == []
        assert SliderArbiter(ws, "s").resolve(70.0) == 70.0


class TestRendererIntVariant:
    def test_int_variant_commits_an_int_and_reconciles_exactly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # INT-VARIANT: slider_int returns an int; the committed ValueChanged
        # carries the int, and float(int) reconciles exactly through the window.
        fake = _FakeImgui(
            _Frame(dragged=7.0, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _slider(value=0.0, integer=True)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = SliderRenderer(WidgetState())

        renderer.render(elem)  # dragging to 7
        renderer.render(elem)  # release -> commit fires int 7
        renderer.render(elem)  # idle; pre-echo 0 -> optimistic committed 7

        assert [e.value for e in fired] == [7]
        assert isinstance(fired[0].value, int)
        assert fake.recorded == [0.0, 7.0, 7.0]
