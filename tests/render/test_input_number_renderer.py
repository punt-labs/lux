"""InputNumberRenderer + the shared ContinuousEditArbiter under the commit-echo rule.

The pure honour-or-defer decision is the shared ``ContinuousEditArbiter`` (tested
in ``test_slider_renderer`` / ``test_continuous_edit_accessors`` over the same
``FloatValueAccessor`` this renderer reuses); here the paint-seam tests drive a
scripted fake imgui. ``input_number`` carries a ``float`` where the ``integer``
variant coerces to ``int`` at the ``input_int`` widget seam.

The renderer-specific case the slider suite cannot have is the **step button**: a
discrete change on a non-active frame must commit exactly once (the fallback
trigger), and a frame satisfying *both* the deactivate and the discrete condition
must still fire exactly once (the two conditions feed one ``if``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import input_number_renderer
from punt_lux.display.renderers.imgui.continuous_edit_accessors import (
    FloatValueAccessor,
)
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.display.renderers.input_number_renderer import InputNumberRenderer
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


def _arb(state: WidgetState, element_id: str) -> ContinuousEditArbiter[float]:
    """Build the shared arbiter with the reused float accessor."""
    return ContinuousEditArbiter(state, element_id, FloatValueAccessor())


@dataclass(frozen=True, slots=True)
class _Frame:
    """One scripted imgui frame.

    ``edited`` is the value the user typed/stepped this frame — ``None`` means no
    change, so imgui echoes the position it was handed. ``active`` and
    ``committed`` are the item-state flags queried after the widget is submitted.
    """

    edited: float | None
    active: bool
    committed: bool


class _FakeImgui:
    """Fake imgui returning one scripted ``_Frame`` per ``input_*`` call.

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

    def input_float(
        self, _label: str, current: float, _step: float, _step_fast: float, _fmt: str
    ) -> tuple[bool, float]:
        return self._advance(current)

    def input_int(
        self, _label: str, current: int, _step: int, _step_fast: int
    ) -> tuple[bool, int]:
        changed, value = self._advance(float(current))
        return (changed, int(value))

    def _advance(self, current: float) -> tuple[bool, float]:
        self.recorded.append(current)
        frame = self._frames[self._index]
        self._index += 1
        self._current = frame
        value = current if frame.edited is None else frame.edited
        return (frame.edited is not None, value)

    def is_item_active(self) -> bool:
        return self._current.active

    def is_item_deactivated_after_edit(self) -> bool:
        return self._current.committed


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(input_number_renderer, "imgui", fake)


def _number(
    *, value: float = 0.0, integer: bool = False, step: float | None = None
) -> InputNumberElement:
    return InputNumberElement(
        id="n", label="Qty", value=value, min=0.0, max=100.0, integer=integer, step=step
    )


class TestRendererHonour:
    def test_idle_frames_track_the_hub_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-WHEN-IDLE: two idle re-push frames with different values; the
        # position handed to imgui tracks each.
        fake = _FakeImgui(
            _Frame(edited=None, active=False, committed=False),
            _Frame(edited=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(_number(value=42.0))
        renderer.render(_number(value=63.5))

        assert fake.recorded == [42.0, 63.5]


class TestRendererDefer:
    def test_hub_drive_while_typing_does_not_clobber(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-CLOBBER: the user types 30 (frame 1), then a Hub re-push carries
        # value=99 while the field is still active (frame 2). The position handed
        # to imgui stays 30, not 99.
        fake = _FakeImgui(
            _Frame(edited=30.0, active=True, committed=False),
            _Frame(edited=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(_number(value=0.0))
        renderer.render(_number(value=99.0))

        assert fake.recorded == [0.0, 30.0]

    def test_grab_without_edit_still_honours_a_hub_drive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-DISCIPLINE: an active frame with no edit (frame 1) does not begin
        # deferring, so a Hub re-push (frame 2) still reaches the field.
        fake = _FakeImgui(
            _Frame(edited=None, active=True, committed=False),
            _Frame(edited=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(_number(value=42.0))
        renderer.render(_number(value=63.5))

        assert fake.recorded == [42.0, 63.5]


class TestRendererCommit:
    def test_commit_after_edit_fires_once_with_the_final_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # COMMIT-ON-IDLE: edit frames fire nothing; the deactivate frame fires
        # exactly one ValueChanged carrying the final float.
        fake = _FakeImgui(
            _Frame(edited=75.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _number(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)
        assert fired == []  # edit frame does not fire

        renderer.render(elem)
        assert len(fired) == 1
        assert fired[0].value == 75.0
        assert fired[0].element_id == "n"

    def test_no_fire_while_merely_typing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # NO-FIRE-WHILE-EDITING: three active edit frames, no deactivate — nothing
        # fires until the edit commits.
        fake = _FakeImgui(
            _Frame(edited=10.0, active=True, committed=False),
            _Frame(edited=20.0, active=True, committed=False),
            _Frame(edited=30.0, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _number(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)
        renderer.render(elem)

        assert fired == []


class TestRendererPostCommit:
    def test_idle_after_commit_shows_the_committed_value_until_the_echo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # POST-COMMIT LATENCY: edit -> commit -> idle while elem.value is still the
        # pre-echo Hub value -> the echo arrives. Through the window the field
        # honours the COMMITTED value, then honours the Hub once it echoes.
        fake = _FakeImgui(
            _Frame(edited=80.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
            _Frame(edited=None, active=False, committed=False),
            _Frame(edited=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _number(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)  # editing
        renderer.render(elem)  # commit fires once
        renderer.render(elem)  # idle; elem.value still pre-echo 0
        renderer.render(_number(value=80.0))  # the Hub echo landed

        assert [e.value for e in fired] == [80.0]
        assert fake.recorded == [0.0, 80.0, 80.0, 80.0]

    def test_edit_in_the_window_wins_over_the_pending_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # EDIT-IN-WINDOW-WINS: commit 80 (echo in flight), then re-focus and type
        # 33 while the record is live. The live buffer is authoritative.
        fake = _FakeImgui(
            _Frame(edited=80.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
            _Frame(edited=33.0, active=True, committed=False),
            _Frame(edited=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _number(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)  # editing
        renderer.render(elem)  # commit 80; record live
        renderer.render(elem)  # re-focus, type 33: buffer authoritative
        renderer.render(elem)  # still active: the live buffer wins

        assert [e.value for e in fired] == [80.0]
        assert fake.recorded == [0.0, 80.0, 80.0, 33.0]


class TestRendererRemoval:
    def test_removal_mid_edit_drops_the_buffer_without_committing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An input removed mid-edit drops its buffer via discard_for and never
        # reaches the commit path, so no ValueChanged fires.
        fake = _FakeImgui(_Frame(edited=30.0, active=True, committed=False))
        _install(monkeypatch, fake)
        ws = WidgetState()
        elem = _number(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(ws)

        renderer.render(elem)  # editing: buffer set to 30
        ws.discard_for("n")  # the element is removed mid-edit

        assert fired == []
        assert _arb(ws, "n").resolve(70.0) == 70.0


class TestRendererIntVariant:
    def test_int_variant_commits_an_int_and_reconciles_exactly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # INT-VARIANT: input_int returns an int; the committed ValueChanged carries
        # the int, and float(int) reconciles exactly through the window.
        fake = _FakeImgui(
            _Frame(edited=7.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
            _Frame(edited=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _number(value=0.0, integer=True)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)  # editing to 7
        renderer.render(elem)  # commit fires int 7
        renderer.render(elem)  # idle; pre-echo 0 -> optimistic committed 7

        assert [e.value for e in fired] == [7]
        assert isinstance(fired[0].value, int)
        assert fake.recorded == [0.0, 7.0, 7.0]


class TestRendererClamp:
    def test_over_max_entry_clamps_the_fired_committed_and_shown_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # CLAMP-OVER-MAX: the user types 150 into a [0, 100] field. input_float
        # does not clamp at the widget, so the renderer clamps to 100 before
        # observe/commit/fire. The buffer shown next frame, and the committed and
        # fired value, are all 100 — never 150 — so Hub and Display cannot diverge.
        fake = _FakeImgui(
            _Frame(edited=150.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        ws = WidgetState()
        elem = _number(value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(ws)

        renderer.render(elem)  # editing to 150 -> buffer clamped to 100
        renderer.render(elem)  # deactivate -> commit fires the clamped 100

        assert [e.value for e in fired] == [100.0]
        # The displayed position converges to the clamped buffer, not 150.
        assert fake.recorded == [0.0, 100.0]
        # No divergence: the committed 100 is honoured through the echo window,
        # then forgotten once the Hub echoes 100 (no honour-forever on a stale 150).
        assert _arb(ws, "n").resolve(0.0) == 100.0
        assert _arb(ws, "n").resolve(100.0) == 100.0

    def test_under_min_entry_clamps_up_to_the_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # CLAMP-UNDER-MIN: typing -50 into [0, 100] clamps up to the floor, 0.
        fake = _FakeImgui(
            _Frame(edited=-50.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _number(value=10.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)

        assert [e.value for e in fired] == [0.0]

    def test_unbounded_field_passes_the_value_through_unclamped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # UNBOUNDED: with min=max=None every finite entry is honoured untouched.
        fake = _FakeImgui(
            _Frame(edited=150.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = InputNumberElement(id="n", label="Qty", value=0.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)

        assert [e.value for e in fired] == [150.0]

    def test_int_variant_clamps_to_the_integral_bound_and_stays_int(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # CLAMP-INT: an over-max integer entry clamps to the (validated integral)
        # max and the fired payload stays an ``int``, not the float bound.
        fake = _FakeImgui(
            _Frame(edited=150.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _number(value=0.0, integer=True)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)

        assert fired[0].value == 100
        assert isinstance(fired[0].value, int)


class TestRendererStepper:
    def test_discrete_stepper_change_commits_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # STEPPER FALLBACK: a stepper click reports changed=True on a frame that is
        # not active and does not deactivate; the fallback condition commits it
        # exactly once.
        fake = _FakeImgui(_Frame(edited=6.0, active=False, committed=False))
        _install(monkeypatch, fake)
        elem = _number(value=5.0, integer=True, step=1.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)

        assert [e.value for e in fired] == [6]

    def test_frame_satisfying_both_conditions_fires_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # MUTUAL EXCLUSIVITY: a frame where the stepper release both deactivates
        # AND reports a discrete change satisfies both commit conditions; the
        # single ``if`` fires exactly once, never twice.
        fake = _FakeImgui(_Frame(edited=6.0, active=False, committed=True))
        _install(monkeypatch, fake)
        elem = _number(value=5.0, integer=True, step=1.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)

        assert len(fired) == 1
        assert fired[0].value == 6

    def test_stepper_hold_then_release_commits_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A held stepper is active while repeating (observe), then a release frame
        # deactivates and commits once — one commit per gesture, like typing.
        fake = _FakeImgui(
            _Frame(edited=6.0, active=True, committed=False),
            _Frame(edited=7.0, active=True, committed=False),
            _Frame(edited=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _number(value=5.0, integer=True, step=1.0)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputNumberRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)
        renderer.render(elem)

        assert [e.value for e in fired] == [7]
