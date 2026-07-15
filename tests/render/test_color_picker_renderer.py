"""ColorPickerRenderer + ColorPickerArbiter under the commit-echo rule.

The pure ``ColorPickerArbiter`` honour-or-defer decision is tested here without
imgui; the renderer paint-seam tests drive a scripted fake imgui. The picker
carries an arity-4 RGBA ``tuple`` where ``slider`` carries a ``float`` and
``input_text`` a ``str``; the reconciliation logic is identical, so the
invariants mirror those suites, each fidelity-checked against the naive it beats.

Tuple-specific cases the scalar suites cannot have:

- EXACT-EQUALITY — commit the quantized (8-bit round-tripped) tuple, echo the
  same tuple, assert the window closes; a bit-distinct neighbour is honoured
  immediately. This is the executable form of the atomic-echo argument.
- SIGNED-ZERO — a ``-0.0`` channel compares equal to ``0.0``, so a commit whose
  echo flips the sign still closes its window.
- MULTI-SUB-CONTROL — the color_edit/color_picker sub-controls each fire an
  independent deactivate, so a gesture across the SV square then the hue bar
  commits the whole color once per sub-control release (amendment: sequential
  whole-color commits, never a partial).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import color_picker_renderer
from punt_lux.display.renderers.color_picker_renderer import ColorPickerRenderer
from punt_lux.display.renderers.imgui.color_picker_selection import ColorPickerArbiter
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest

_RED: Rgba = (1.0, 0.0, 0.0, 1.0)
_BLUE: Rgba = (0.0, 0.0, 1.0, 1.0)
_GREEN: Rgba = (0.0, 1.0, 0.0, 1.0)
_GREY: Rgba = (0.5, 0.5, 0.5, 1.0)


# -- the arbiter: the pure honour-or-defer decision ------------------------


class TestArbiterResolve:
    def test_idle_resolves_to_the_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: a fresh (idle) picker renders the Hub color.
        arb = ColorPickerArbiter(WidgetState(), "c")
        assert arb.resolve(_RED) == _RED

    def test_idle_tracks_the_latest_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: each idle frame honours the current Hub color, so an
        # agent-driven change is picked up without any per-channel bookkeeping.
        arb = ColorPickerArbiter(WidgetState(), "c")
        assert arb.resolve(_RED) == _RED
        assert arb.resolve(_BLUE) == _BLUE

    def test_dragging_defers_to_the_local_buffer(self) -> None:
        # NO-CLOBBER: once a frame has observed a real drag, a Hub-driven color
        # is ignored — the in-progress color wins.
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.observe(edited=True, value=_GREEN)
        assert arb.resolve(_BLUE) == _GREEN
        assert arb.resolve(_BLUE) == _GREEN

    def test_grab_without_drag_keeps_honouring(self) -> None:
        # HONOUR-DISCIPLINE: an active frame with no real drag does not begin
        # deferring — the picker still honours the Hub, so an echo can reach it.
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.observe(edited=False, value=_RED)
        assert arb.resolve(_BLUE) == _BLUE

    def test_release_returns_to_honouring_the_hub(self) -> None:
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.observe(edited=True, value=_GREEN)
        arb.release()
        assert arb.resolve(_BLUE) == _BLUE

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        ColorPickerArbiter(ws, "a").observe(edited=True, value=_GREEN)
        assert ColorPickerArbiter(ws, "a").resolve(_RED) == _GREEN
        assert ColorPickerArbiter(ws, "b").resolve(_BLUE) == _BLUE

    def test_editing_branch_returns_arity_four_from_a_three_tuple_store(self) -> None:
        # resolve's editing branch returns the buffer uncoerced via get_tuple,
        # which normalizes a length-3 store to arity 4 — so tuple == stays sound.
        ws = WidgetState()
        arb = ColorPickerArbiter(ws, "c")
        arb.observe(edited=True, value=_GREEN)
        ws.set(f"c{WidgetState.COLOR_BUFFER_SUFFIX}", (0.2, 0.4, 0.6))
        assert arb.resolve(_RED) == (0.2, 0.4, 0.6, 1.0)


class TestArbiterCommitEcho:
    def test_commit_is_honoured_until_the_hub_value_moves(self) -> None:
        # REFOCUS-DURABILITY: after commit, an idle frame whose Hub color is still
        # the pre-echo color renders the committed color — the optimistic echo.
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_GREY)
        assert arb.resolve(_GREY) == _GREEN
        assert arb.resolve(_GREY) == _GREEN

    def test_commit_record_clears_once_the_echo_arrives(self) -> None:
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_GREY)
        assert arb.resolve(_GREEN) == _GREEN  # echo landed: Hub == committed
        assert arb.resolve(_RED) == _RED  # record gone: honour the Hub

    def test_dragging_wins_over_a_pending_commit(self) -> None:
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_GREY)
        arb.observe(edited=True, value=_BLUE)
        assert arb.resolve(_GREY) == _BLUE

    def test_agent_override_mid_window_drops_the_committed_value(self) -> None:
        # AGENT-OVERRIDE-MID-WINDOW: the commit-hub marker is load-bearing. Commit
        # GREEN while the Hub holds a DISTINCT non-default pre-echo BLUE; the
        # window honours GREEN while the Hub reads BLUE, but an override that
        # drives the Hub to a THIRD color drops the committed value and honours
        # the Hub. A wrong impl comparing hub against committed would keep GREEN.
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_BLUE)
        assert arb.resolve(_BLUE) == _GREEN  # window open, Hub still pre-echo BLUE
        assert arb.resolve(_GREY) == _GREY  # override to a third color: honour Hub


class TestArbiterTupleEquality:
    def test_quantized_commit_echo_closes_the_window(self) -> None:
        # EXACT-EQUALITY: commit the quantized tuple (from_hex of the fired hex);
        # the echo is the Hub moving to that same from_hex tuple, which differs
        # from the commit-time hub — so resolve takes the FORGET branch and
        # returns the raw Hub value, bit-for-bit the quantized tuple, no epsilon.
        hex_val = RgbaColor((0.1 + 0.2, 0.7, 0.333333, 1.0)).to_hex(alpha=False)
        quantized = RgbaColor.from_hex(hex_val).as_tuple()
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.commit(quantized, hub_value=_GREY)
        assert arb.resolve(_GREY) == quantized  # window open: honour committed
        assert arb.resolve(quantized) == quantized  # echo: Hub moved off commit-hub
        assert arb.resolve(_RED) == _RED  # record cleared: honour the Hub

    def test_bit_distinct_neighbour_is_honoured_immediately(self) -> None:
        # A neighbour one ULP away in a single channel is a genuine agent
        # override, honoured at once — tuple == would not mask it.
        arb = ColorPickerArbiter(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=(0.3, 0.3, 0.3, 1.0))
        neighbour = (0.30000000000000004, 0.3, 0.3, 1.0)
        assert arb.resolve(neighbour) == neighbour

    def test_signed_zero_channel_echo_closes_the_window(self) -> None:
        # -0.0 == 0.0 in IEEE-754, so a commit with a -0.0 channel whose echo
        # returns 0.0 still recognises the echo and closes the window.
        arb = ColorPickerArbiter(WidgetState(), "c")
        commit_hub = (-0.0, 0.0, 0.0, 1.0)
        arb.commit(_GREEN, hub_value=commit_hub)
        assert arb.resolve((0.0, 0.0, 0.0, 1.0)) == _GREEN  # echo == commit-hub
        assert arb.resolve(_RED) == _RED  # record cleared


# -- fidelity: the naive implementations each invariant must beat ----------


class _HonourEveryFrameArbiter:
    """Naive: render the Hub color every frame, ignoring that the user drags."""

    def resolve(self, hub_value: Rgba) -> Rgba:
        return hub_value

    def observe(self, *, edited: bool, value: Rgba) -> None:
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

    def resolve(self, hub_value: Rgba) -> Rgba:
        if self._state.get(self._key) is None:
            self._state.set(self._key, hub_value)
        return self._state.get_tuple(self._key, default=hub_value)


class TestArbiterFidelity:
    def test_honour_every_frame_clobbers_the_live_color(self) -> None:
        naive = _HonourEveryFrameArbiter()
        naive.observe(edited=True, value=_GREEN)
        assert naive.resolve(_BLUE) == _BLUE  # clobbered — the bug

        real = ColorPickerArbiter(WidgetState(), "c")
        real.observe(edited=True, value=_GREEN)
        assert real.resolve(_BLUE) == _GREEN  # deferred — the fix

    def test_seed_once_ignores_a_later_idle_hub_drive(self) -> None:
        naive = _SeedOnceArbiter(WidgetState(), "c")
        assert naive.resolve(_RED) == _RED
        assert naive.resolve(_BLUE) == _RED  # stale — the bug

        real = ColorPickerArbiter(WidgetState(), "c")
        assert real.resolve(_RED) == _RED
        assert real.resolve(_BLUE) == _BLUE  # honoured — the fix


class TestRemovalMidDrag:
    def test_removal_mid_drag_drops_the_buffer(self) -> None:
        ws = WidgetState()
        arb = ColorPickerArbiter(ws, "c")
        arb.observe(edited=True, value=_GREEN)
        assert arb.resolve(_BLUE) == _GREEN  # buffer wins while dragging

        ws.discard_for("c")  # the element is removed mid-drag

        assert ColorPickerArbiter(ws, "c").resolve(_RED) == _RED

    def test_removal_clears_a_pending_commit_echo(self) -> None:
        ws = WidgetState()
        arb = ColorPickerArbiter(ws, "c")
        arb.commit(_GREEN, hub_value=_GREY)
        assert arb.resolve(_GREY) == _GREEN  # pending: honour the committed color

        ws.discard_for("c")  # removed while the echo is pending

        assert ColorPickerArbiter(ws, "c").resolve(_RED) == _RED


# -- the renderer: honour idle, defer dragging, commit once ----------------


@dataclass(frozen=True, slots=True)
class _Frame:
    """One scripted imgui frame.

    ``dragged`` is the color the user dragged to this frame — ``None`` means no
    drag, so imgui echoes the color it was handed. ``active`` and ``committed``
    are the item-state flags queried after the widget is submitted.
    """

    dragged: Rgba | None
    active: bool
    committed: bool


class _FakeImgui:
    """Fake imgui returning one scripted ``_Frame`` per ``color_*`` call.

    ``recorded`` is the sequence of colors ``render`` handed to the widget — the
    honour/defer evidence (always an arity-4 tuple for a clean diff).
    """

    recorded: list[Rgba]
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

    def color_edit3(self, _label: str, current: object) -> tuple[bool, Rgba]:
        return self._advance(current)

    def color_edit4(self, _label: str, current: object) -> tuple[bool, Rgba]:
        return self._advance(current)

    def color_picker3(self, _label: str, current: object) -> tuple[bool, Rgba]:
        return self._advance(current)

    def color_picker4(self, _label: str, current: object) -> tuple[bool, Rgba]:
        return self._advance(current)

    def _advance(self, current: object) -> tuple[bool, Rgba]:
        as_tuple: Rgba = (
            float(current[0]),  # type: ignore[index]
            float(current[1]),  # type: ignore[index]
            float(current[2]),  # type: ignore[index]
            float(current[3]),  # type: ignore[index]
        )
        self.recorded.append(as_tuple)
        frame = self._frames[self._index]
        self._index += 1
        self._current = frame
        value = as_tuple if frame.dragged is None else frame.dragged
        return (frame.dragged is not None, value)

    def is_item_active(self) -> bool:
        return self._current.active

    def is_item_deactivated_after_edit(self) -> bool:
        return self._current.committed


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(color_picker_renderer, "imgui", fake)


def _picker(*, value: str = "#000000", alpha: bool = False) -> ColorPickerElement:
    return ColorPickerElement(id="c", label="Bg", value=value, alpha=alpha)


class TestRendererHonour:
    def test_idle_frames_track_the_hub_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-WHEN-IDLE: two idle re-push frames with different values; the
        # color handed to imgui tracks each.
        fake = _FakeImgui(
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_picker(value="#FF0000"))
        renderer.render(_picker(value="#0000FF"))

        assert fake.recorded == [_RED, _BLUE]


class TestRendererDefer:
    def test_hub_drive_while_dragging_does_not_clobber(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-CLOBBER: the user drags to GREEN (frame 1), then a Hub re-push
        # carries blue while the control is still active (frame 2). The color
        # handed to imgui stays GREEN, not blue.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_picker(value="#000000"))
        renderer.render(_picker(value="#0000FF"))

        assert fake.recorded == [(0.0, 0.0, 0.0, 1.0), _GREEN]

    def test_grab_without_drag_still_honours_a_hub_drive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-DISCIPLINE: an active frame with no drag (frame 1) does not begin
        # deferring, so a Hub re-push (frame 2) still reaches the control.
        fake = _FakeImgui(
            _Frame(dragged=None, active=True, committed=False),
            _Frame(dragged=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_picker(value="#FF0000"))
        renderer.render(_picker(value="#0000FF"))

        assert fake.recorded == [_RED, _BLUE]


class TestRendererCommit:
    def test_release_after_drag_fires_once_with_the_hex(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # COMMIT-ON-RELEASE: drag frames fire nothing; the release frame fires
        # exactly one ValueChanged carrying the committed hex string.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)
        assert fired == []  # drag frame does not fire

        renderer.render(elem)
        assert len(fired) == 1
        assert fired[0].value == "#00FF00"
        assert fired[0].element_id == "c"

    def test_no_fire_while_merely_dragging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-FIRE-WHILE-DRAGGING: three active drag frames, no release — nothing
        # fires until the drag commits.
        fake = _FakeImgui(
            _Frame(dragged=_RED, active=True, committed=False),
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=_BLUE, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)
        renderer.render(elem)

        assert fired == []


class TestRendererMultiSubControl:
    def test_two_sub_control_releases_commit_the_whole_color_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # MULTI-SUB-CONTROL: the SV square releases (commit GREEN), then the hue
        # bar releases (commit BLUE). Each sub-control fires its own independent
        # deactivate, so the arbiter records TWO sequential whole-color commits,
        # each a complete hex — never a partial channel update.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),  # drag SV square
            _Frame(dragged=None, active=False, committed=True),  # SV release: commit
            _Frame(dragged=_BLUE, active=True, committed=False),  # drag hue bar
            _Frame(dragged=None, active=False, committed=True),  # hue release: commit
        )
        _install(monkeypatch, fake)
        elem = _picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        for _ in range(4):
            renderer.render(elem)

        assert [e.value for e in fired] == ["#00FF00", "#0000FF"]


class TestRendererPostCommit:
    def test_idle_after_commit_shows_the_committed_color_until_the_echo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # POST-COMMIT LATENCY: drag -> release/commit -> idle while elem.value is
        # still the pre-echo Hub color -> the echo arrives. Through the window the
        # control honours the COMMITTED color, then honours the Hub once it echoes.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _picker(value="#000000")  # pre-echo Hub color
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)  # dragging
        renderer.render(elem)  # release -> commit fires once
        renderer.render(elem)  # idle; elem.value still pre-echo black
        renderer.render(_picker(value="#00FF00"))  # the Hub echo landed

        assert [e.value for e in fired] == ["#00FF00"]  # exactly one commit fire
        black = (0.0, 0.0, 0.0, 1.0)
        assert fake.recorded == [black, _GREEN, _GREEN, _GREEN]

    def test_agent_override_mid_window_tracks_the_hub_not_the_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # AGENT-OVERRIDE-MID-WINDOW: commit GREEN while pre-echo Hub is black; an
        # idle window frame shows committed GREEN, but an agent drive to a
        # divergent third color tracks the Hub, dropping the optimistic echo.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)  # dragging
        renderer.render(elem)  # release -> commit GREEN; commit-hub is black
        renderer.render(elem)  # idle; Hub still black -> optimistic GREEN
        renderer.render(_picker(value="#FF0000"))  # agent override to a third color

        assert [e.value for e in fired] == ["#00FF00"]
        black = (0.0, 0.0, 0.0, 1.0)
        assert fake.recorded == [black, _GREEN, _GREEN, _RED]


class TestRendererRemoval:
    def test_removal_mid_drag_drops_the_buffer_without_committing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A picker removed mid-drag drops its buffer via discard_for and never
        # reaches the release path, so no ValueChanged fires.
        fake = _FakeImgui(_Frame(dragged=_GREEN, active=True, committed=False))
        _install(monkeypatch, fake)
        ws = WidgetState()
        elem = _picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(ws)

        renderer.render(elem)  # dragging: buffer set to GREEN
        ws.discard_for("c")  # the element is removed mid-drag

        assert fired == []
        assert ColorPickerArbiter(ws, "c").resolve(_RED) == _RED


class TestRendererAlphaVariant:
    def test_alpha_variant_commits_an_eight_digit_hex(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The RGBA variant commits a #RRGGBBAA hex carrying the alpha channel.
        translucent: Rgba = (1.0, 0.0, 0.0, 0.502)
        fake = _FakeImgui(
            _Frame(dragged=translucent, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _picker(value="#00000000", alpha=True)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)

        assert [e.value for e in fired] == ["#FF000080"]
