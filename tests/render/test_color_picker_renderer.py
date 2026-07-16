"""ColorPickerRenderer + the shared ContinuousEditArbiter under the commit-echo rule.

The pure honour-or-defer decision is tested here without imgui, driving the
shared ``ContinuousEditArbiter`` with a ``ColorValueAccessor``; the renderer
paint-seam tests drive a scripted fake imgui. The picker
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
from typing import Self

import pytest
from imgui_bundle import ImVec2, imgui

from punt_lux.display.renderers import color_picker_renderer
from punt_lux.display.renderers.color_picker_renderer import ColorPickerRenderer
from punt_lux.display.renderers.imgui import color_channel_strip, full_color_picker
from punt_lux.display.renderers.imgui.continuous_edit_accessors import (
    ColorValueAccessor,
)
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene.widget_state import WidgetState

_RED: Rgba = (1.0, 0.0, 0.0, 1.0)
_BLUE: Rgba = (0.0, 0.0, 1.0, 1.0)
_GREEN: Rgba = (0.0, 1.0, 0.0, 1.0)
_GREY: Rgba = (0.5, 0.5, 0.5, 1.0)


def _arb(state: WidgetState, element_id: str) -> ContinuousEditArbiter[Rgba]:
    """Build the shared arbiter with the color picker's RGBA accessor."""
    return ContinuousEditArbiter(state, element_id, ColorValueAccessor())


# -- the arbiter: the pure honour-or-defer decision ------------------------


class TestArbiterResolve:
    def test_idle_resolves_to_the_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: a fresh (idle) picker renders the Hub color.
        arb = _arb(WidgetState(), "c")
        assert arb.resolve(_RED) == _RED

    def test_idle_tracks_the_latest_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: each idle frame honours the current Hub color, so an
        # agent-driven change is picked up without any per-channel bookkeeping.
        arb = _arb(WidgetState(), "c")
        assert arb.resolve(_RED) == _RED
        assert arb.resolve(_BLUE) == _BLUE

    def test_dragging_defers_to_the_local_buffer(self) -> None:
        # NO-CLOBBER: once a frame has observed a real drag, a Hub-driven color
        # is ignored — the in-progress color wins.
        arb = _arb(WidgetState(), "c")
        arb.observe(edited=True, value=_GREEN)
        assert arb.resolve(_BLUE) == _GREEN
        assert arb.resolve(_BLUE) == _GREEN

    def test_grab_without_drag_keeps_honouring(self) -> None:
        # HONOUR-DISCIPLINE: an active frame with no real drag does not begin
        # deferring — the picker still honours the Hub, so an echo can reach it.
        arb = _arb(WidgetState(), "c")
        arb.observe(edited=False, value=_RED)
        assert arb.resolve(_BLUE) == _BLUE

    def test_release_returns_to_honouring_the_hub(self) -> None:
        arb = _arb(WidgetState(), "c")
        arb.observe(edited=True, value=_GREEN)
        arb.release()
        assert arb.resolve(_BLUE) == _BLUE

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        _arb(ws, "a").observe(edited=True, value=_GREEN)
        assert _arb(ws, "a").resolve(_RED) == _GREEN
        assert _arb(ws, "b").resolve(_BLUE) == _BLUE

    def test_editing_branch_returns_arity_four_from_a_three_tuple_store(self) -> None:
        # resolve's editing branch returns the buffer uncoerced via get_tuple,
        # which normalizes a length-3 store to arity 4 — so tuple == stays sound.
        ws = WidgetState()
        arb = _arb(ws, "c")
        arb.observe(edited=True, value=_GREEN)
        ws.set(f"c{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}", (0.2, 0.4, 0.6))
        assert arb.resolve(_RED) == (0.2, 0.4, 0.6, 1.0)


class TestArbiterCommitEcho:
    def test_commit_is_honoured_until_the_hub_value_moves(self) -> None:
        # REFOCUS-DURABILITY: after commit, an idle frame whose Hub color is still
        # the pre-echo color renders the committed color — the optimistic echo.
        arb = _arb(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_GREY)
        assert arb.resolve(_GREY) == _GREEN
        assert arb.resolve(_GREY) == _GREEN

    def test_commit_record_clears_once_the_echo_arrives(self) -> None:
        arb = _arb(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_GREY)
        assert arb.resolve(_GREEN) == _GREEN  # echo landed: Hub == committed
        assert arb.resolve(_RED) == _RED  # record gone: honour the Hub

    def test_dragging_wins_over_a_pending_commit(self) -> None:
        arb = _arb(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=_GREY)
        arb.observe(edited=True, value=_BLUE)
        assert arb.resolve(_GREY) == _BLUE

    def test_agent_override_mid_window_drops_the_committed_value(self) -> None:
        # AGENT-OVERRIDE-MID-WINDOW: the commit-hub marker is load-bearing. Commit
        # GREEN while the Hub holds a DISTINCT non-default pre-echo BLUE; the
        # window honours GREEN while the Hub reads BLUE, but an override that
        # drives the Hub to a THIRD color drops the committed value and honours
        # the Hub. A wrong impl comparing hub against committed would keep GREEN.
        arb = _arb(WidgetState(), "c")
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
        arb = _arb(WidgetState(), "c")
        arb.commit(quantized, hub_value=_GREY)
        assert arb.resolve(_GREY) == quantized  # window open: honour committed
        assert arb.resolve(quantized) == quantized  # echo: Hub moved off commit-hub
        assert arb.resolve(_RED) == _RED  # record cleared: honour the Hub

    def test_bit_distinct_neighbour_is_honoured_immediately(self) -> None:
        # A neighbour one ULP away in a single channel is a genuine agent
        # override, honoured at once — tuple == would not mask it.
        arb = _arb(WidgetState(), "c")
        arb.commit(_GREEN, hub_value=(0.3, 0.3, 0.3, 1.0))
        neighbour = (0.30000000000000004, 0.3, 0.3, 1.0)
        assert arb.resolve(neighbour) == neighbour

    def test_signed_zero_channel_echo_closes_the_window(self) -> None:
        # -0.0 == 0.0 in IEEE-754, so a commit with a -0.0 channel whose echo
        # returns 0.0 still recognises the echo and closes the window.
        arb = _arb(WidgetState(), "c")
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

        real = _arb(WidgetState(), "c")
        real.observe(edited=True, value=_GREEN)
        assert real.resolve(_BLUE) == _GREEN  # deferred — the fix

    def test_seed_once_ignores_a_later_idle_hub_drive(self) -> None:
        naive = _SeedOnceArbiter(WidgetState(), "c")
        assert naive.resolve(_RED) == _RED
        assert naive.resolve(_BLUE) == _RED  # stale — the bug

        real = _arb(WidgetState(), "c")
        assert real.resolve(_RED) == _RED
        assert real.resolve(_BLUE) == _BLUE  # honoured — the fix


class TestRemovalMidDrag:
    def test_removal_mid_drag_drops_the_buffer(self) -> None:
        ws = WidgetState()
        arb = _arb(ws, "c")
        arb.observe(edited=True, value=_GREEN)
        assert arb.resolve(_BLUE) == _GREEN  # buffer wins while dragging

        ws.discard_for("c")  # the element is removed mid-drag

        assert _arb(ws, "c").resolve(_RED) == _RED

    def test_removal_clears_a_pending_commit_echo(self) -> None:
        ws = WidgetState()
        arb = _arb(ws, "c")
        arb.commit(_GREEN, hub_value=_GREY)
        assert arb.resolve(_GREY) == _GREEN  # pending: honour the committed color

        ws.discard_for("c")  # removed while the echo is pending

        assert _arb(ws, "c").resolve(_RED) == _RED


# -- the renderer: honour idle, defer dragging, commit once ----------------


def _to_255(value: float) -> int:
    """Return one ``[0, 1]`` channel as an 8-bit ``0..255`` int (the strip's map)."""
    return max(0, min(255, round(value * 255.0)))


@dataclass(frozen=True, slots=True)
class _Frame:
    """One scripted imgui frame.

    ``dragged`` is the color the user dragged to this frame — ``None`` means no
    drag, so imgui echoes the color it was handed. ``active`` and ``committed``
    are the item-state flags queried after the widget is submitted.

    ``channel_drag`` matters only on the full-picker path, where two sub-controls
    can move: ``False`` (default) attributes the drag to the SV square (the picker
    reports it, the channel bars stay quiet), ``True`` to a channel bar (the bar
    reports it, the picker stays quiet). Only one sub-control moves per frame.
    """

    dragged: Rgba | None
    active: bool
    committed: bool
    channel_drag: bool = False


class _FakeStyle:
    """The two style fields ``ColorChannelStrip`` reads: inner spacing, rounding."""

    item_inner_spacing: ImVec2
    frame_rounding: float

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.item_inner_spacing = ImVec2(4.0, 4.0)
        self.frame_rounding = 2.0
        return self


class _FakeDrawList:
    """A draw list that records each channel's proportional fill x-extent."""

    fills: list[tuple[float, float]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.fills = []
        return self

    def add_rect_filled(
        self, p_min: ImVec2, p_max: ImVec2, _col: int, _rounding: float = 0.0
    ) -> None:
        """Record ``(x_min, x_max)`` — the value-proportional fill span."""
        self.fills.append((p_min.x, p_max.x))


class _FakeImgui:
    """Fake imgui driving the channel-strip edit path (and the picker path).

    ``recorded`` is the sequence of colors ``render`` handed to the widget — the
    honour/defer evidence (arity-4 tuples). The strip feeds one DragInt per
    channel inside a group; the fake reassembles the resolved-in color from those
    per-channel ints at ``end_group``, so the evidence matches the picker path's
    single-tuple record. One ``_Frame`` is consumed per widget — at
    ``begin_group`` for the strip, at ``color_picker*`` for the picker.
    """

    recorded: list[Rgba]
    picker_flags: list[int]
    channel_flags: list[int]
    draw_list: _FakeDrawList
    _frames: list[_Frame]
    _index: int
    _current: _Frame
    _channel_ins: dict[int, int]
    _depth: int
    _picked: bool

    def __new__(cls, *frames: _Frame) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self.picker_flags = []
        self.channel_flags = []
        self.draw_list = _FakeDrawList()
        self._frames = list(frames)
        self._index = 0
        self._current = frames[0]
        self._channel_ins = {}
        self._depth = 0
        self._picked = False
        return self

    # -- channel-strip surface (the inline edit path) ----------------------

    def push_id(self, _id: str) -> None:
        """No id stack in the fake."""

    def pop_id(self) -> None:
        """No id stack in the fake."""

    def begin_group(self) -> None:
        """Start a group; the outermost consumes the next scripted frame.

        The strip path opens the sole group; the picker path opens an outer group
        wrapping the picker plus the strip's inner group. Frame consumption and
        the channel-input reset happen once, at depth 0, so a single picker frame
        drives both the picker and the nested strip.
        """
        if self._depth == 0:
            self._current = self._frames[self._index]
            self._index += 1
            self._channel_ins = {}
            self._picked = False
        self._depth += 1

    def end_group(self) -> None:
        """Close a group; the outermost strip-path group records its resolved color.

        The picker path records at ``color_picker*`` instead (``_picked`` set), so
        the outer group's close must not double-record.
        """
        self._depth -= 1
        if self._depth == 0 and not self._picked:
            r = self._channel_ins.get(0, 0) / 255.0
            g = self._channel_ins.get(1, 0) / 255.0
            b = self._channel_ins.get(2, 0) / 255.0
            a = self._channel_ins[3] / 255.0 if 3 in self._channel_ins else 1.0
            self.recorded.append((r, g, b, a))

    def get_style(self) -> _FakeStyle:
        return _FakeStyle()

    def get_frame_height(self) -> float:
        return 20.0

    def calc_item_width(self) -> float:
        # 212 - (frame_h 20 + count 3 * spacing 4) = 180 -> three equal 60px
        # channels, so a fill's x-extent is 60 * value/255 with no width rounding.
        return 212.0

    def get_window_draw_list(self) -> _FakeDrawList:
        return self.draw_list

    def get_color_u32(self, _col: object) -> int:
        return 0

    def get_cursor_screen_pos(self) -> ImVec2:
        return ImVec2(0.0, 0.0)

    def push_style_color(self, _idx: int, _col: object) -> None:
        """The transparent-frame push is invisible to the value-only seam."""

    def pop_style_color(self, _count: int = 1) -> None:
        """Pair the transparent-frame pop."""

    def same_line(self, _offset: float = 0.0, _spacing: float = -1.0) -> None:
        """Layout is not asserted."""

    def set_next_item_width(self, _width: float) -> None:
        """Layout is not asserted."""

    def push_item_width(self, _width: float) -> None:
        """Item width is not asserted by the value-only seam."""

    def pop_item_width(self) -> None:
        """Pair the item-width push."""

    def text(self, _text: str) -> None:
        """The label paint is not asserted."""

    def color_button(
        self, _desc_id: str, _col: object, _flags: int = 0, _size: object = None
    ) -> bool:
        """The preview swatch never registers a click in the fake."""
        return False

    def drag_int(
        self,
        label: str,
        v: int,
        _speed: float = 1.0,
        _lo: int = 0,
        _hi: int = 0,
        _fmt: str = "%d",
        flags: int = 0,
    ) -> tuple[bool, int]:
        """Record the resolved-in channel and its clamp flags; return the drag.

        On the picker path (``_picked`` set), a channel bar edits only on a
        ``channel_drag`` frame — an SV-square drag leaves every channel quiet.
        """
        idx = int(label.removeprefix("##c"))
        self._channel_ins[idx] = v
        self.channel_flags.append(flags)
        frame = self._current
        if self._picked:
            if frame.channel_drag and frame.dragged is not None:
                return (True, _to_255(frame.dragged[idx]))
            return (False, v)
        if frame.dragged is None:
            return (False, v)
        return (True, _to_255(frame.dragged[idx]))

    # -- picker surface (the full-picker path) -----------------------------

    def color_picker3(
        self, _label: str, current: object, flags: int = 0
    ) -> tuple[bool, Rgba]:
        self.picker_flags.append(flags)
        return self._pick(current)

    def color_picker4(
        self, _label: str, current: object, flags: int = 0, _ref: object = None
    ) -> tuple[bool, Rgba]:
        self.picker_flags.append(flags)
        return self._pick(current)

    def _pick(self, current: object) -> tuple[bool, Rgba]:
        """Record the color handed to the picker; return the SV-square drag if any.

        The frame was consumed by the enclosing ``begin_group``, so ``_pick`` reads
        ``self._current`` rather than advancing. On a ``channel_drag`` frame the
        picker is quiet — the channel bar owns the edit.
        """
        as_tuple: Rgba = (
            float(current[0]),  # type: ignore[index]
            float(current[1]),  # type: ignore[index]
            float(current[2]),  # type: ignore[index]
            float(current[3]),  # type: ignore[index]
        )
        self.recorded.append(as_tuple)
        self._picked = True
        frame = self._current
        if frame.channel_drag:
            return (False, as_tuple)
        value = as_tuple if frame.dragged is None else frame.dragged
        return (frame.dragged is not None, value)

    # -- item state (aggregated over the group / picker) -------------------

    def is_item_active(self) -> bool:
        return self._current.active

    def is_item_deactivated_after_edit(self) -> bool:
        return self._current.committed


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(color_picker_renderer, "imgui", fake)
    monkeypatch.setattr(color_channel_strip, "imgui", fake)
    monkeypatch.setattr(full_color_picker, "imgui", fake)


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
        # MULTI-SUB-CONTROL: one channel bar releases (commit GREEN), then another
        # releases (commit BLUE). Each channel fires its own independent deactivate,
        # so the arbiter records TWO sequential whole-color commits, each a complete
        # hex — never a partial channel update.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),  # drag a channel
            _Frame(dragged=None, active=False, committed=True),  # release: commit
            _Frame(dragged=_BLUE, active=True, committed=False),  # drag a channel
            _Frame(dragged=None, active=False, committed=True),  # release: commit
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
        assert _arb(ws, "c").resolve(_RED) == _RED


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


class TestChannelFillScalesWithValue:
    """The fix: each channel's colored fill x-extent scales 0..255 -> 0..width.

    The regression was a fixed-width color *marker* (ColorEdit's 3px channel tab)
    that never moved with the value. These tests read the recorded fill spans and
    prove the span is now value-proportional, not constant.
    """

    def test_fill_extent_is_proportional_to_each_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An idle frame draws one fill per channel, in R, G, B order, each an
        # x-span of 60 * value/255 over its 60px field.
        fake = _FakeImgui(_Frame(dragged=None, active=False, committed=False))
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_picker(value="#FF3399"))  # R=255, G=51, B=153

        spans = [x_max - x_min for x_min, x_max in fake.draw_list.fills]
        assert len(spans) == 3
        assert spans[0] == pytest.approx(60.0 * 255 / 255)
        assert spans[1] == pytest.approx(60.0 * 51 / 255)
        assert spans[2] == pytest.approx(60.0 * 153 / 255)

    def test_a_larger_channel_value_yields_a_wider_fill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact operator scenario: R=216 vs R=37 must NOT render the same
        # sliver. Two idle frames, the R fill span tracks the value.
        fake = _FakeImgui(
            _Frame(dragged=None, active=False, committed=False),
            _Frame(dragged=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_picker(value="#D80000"))  # R=216
        renderer.render(_picker(value="#250000"))  # R=37

        r_high = fake.draw_list.fills[0][1] - fake.draw_list.fills[0][0]
        r_low = fake.draw_list.fills[1][1] - fake.draw_list.fills[1][0]
        assert r_high > r_low
        assert r_high == pytest.approx(60.0 * 216 / 255)
        assert r_low == pytest.approx(60.0 * 37 / 255)


class TestChannelInputIsClamped:
    """Each channel DragInt carries AlwaysClamp so typed input stays 0..255.

    Without the flag ImGui clamps dragging but not Ctrl+click typed input, so a
    typed 999 would flow into the returned tuple and paint the fill past the
    field. AlwaysClamp holds the declared channel bounds on every input path.
    """

    def test_every_channel_drag_int_sets_always_clamp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        always_clamp = imgui.SliderFlags_.always_clamp.value
        fake = _FakeImgui(_Frame(dragged=None, active=False, committed=False))
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_picker(value="#FF3399"))  # three RGB channels

        assert len(fake.channel_flags) == 3
        assert all(flags & always_clamp for flags in fake.channel_flags)


class TestRendererPickerVariant:
    def test_picker_true_routes_through_color_picker_and_commits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The full-picker variant keeps ImGui's color_picker3 (SV square, hue bar,
        # hex) and now routes its RGB channels through the strip; an SV-square drag
        # then release still commits exactly one hex via the unchanged seam.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = ColorPickerElement(id="c", label="Bg", value="#000000", picker=True)
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)

        assert [e.value for e in fired] == ["#00FF00"]
        assert fake.recorded == [(0.0, 0.0, 0.0, 1.0), _GREEN]
        # The picker path now draws value-scaled channel fills through the strip —
        # here only GREEN's G=255 (60px) each frame; R=B=0 draw nothing.
        spans = [x_max - x_min for x_min, x_max in fake.draw_list.fills]
        assert spans == [pytest.approx(60.0), pytest.approx(60.0)]


def _full_picker(*, value: str = "#000000", alpha: bool = False) -> ColorPickerElement:
    """Build the full-picker (``picker=True``) variant."""
    return ColorPickerElement(id="c", label="Bg", value=value, picker=True, alpha=alpha)


class TestPickerChannelFill:
    """The fix on the full-picker path: RGB channels fill proportional to value.

    Stock ``color_picker3`` drew the RGB inputs with the same fixed-3px markers
    that plagued the inline path — R=68/G=47/B=94 all identical slivers. The
    picker now routes those channels through ``ColorChannelStrip``, so their fills
    scale with the value exactly as the inline path does.
    """

    def test_picker_channels_fill_proportional_to_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One idle full-picker frame draws one fill per channel, R, G, B, each an
        # x-span of 60 * value/255 — not three identical slivers.
        fake = _FakeImgui(_Frame(dragged=None, active=False, committed=False))
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_full_picker(value="#FF3399"))  # R=255, G=51, B=153

        spans = [x_max - x_min for x_min, x_max in fake.draw_list.fills]
        assert len(spans) == 3
        assert spans[0] == pytest.approx(60.0 * 255 / 255)
        assert spans[1] == pytest.approx(60.0 * 51 / 255)
        assert spans[2] == pytest.approx(60.0 * 153 / 255)


class TestPickerFlagsDisableRightClickMenu:
    """The picker is submitted with ``NoOptions``, disabling the right-click menu.

    ``DisplayHex`` keeps only the markerless hex row, but the stock right-click
    context menu can switch the display mode back to RGB/HSV, re-exposing the
    fixed-3px channel markers that hex-only display exists to suppress.
    ``NoOptions`` removes that menu, locking the markerless display.
    """

    def test_picker_is_submitted_with_no_options_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        no_options = imgui.ColorEditFlags_.no_options.value
        fake = _FakeImgui(_Frame(dragged=None, active=False, committed=False))
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_full_picker(value="#FF3399"))

        assert fake.picker_flags  # the picker seam was exercised
        assert all(flags & no_options for flags in fake.picker_flags)

    def test_alpha_picker_is_submitted_with_no_options_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The color_picker4 (alpha) path carries the same NoOptions lock.
        no_options = imgui.ColorEditFlags_.no_options.value
        fake = _FakeImgui(_Frame(dragged=None, active=False, committed=False))
        _install(monkeypatch, fake)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(_full_picker(value="#FF3399", alpha=True))

        assert fake.picker_flags
        assert all(flags & no_options for flags in fake.picker_flags)


class TestPickerCommitPerSubControl:
    """One commit per release, whichever full-picker sub-control the user moved.

    Both the picker (SV square / hue bar / hex) and the channel strip live in one
    enclosing group, so the renderer's single ``is_item_*`` read aggregates over
    both — a release on either fires exactly one ValueChanged, never zero (mid
    drag) and never two.
    """

    def test_sv_square_drag_commits_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An SV-square drag to GREEN (the picker reports it, channels stay quiet)
        # then release fires exactly one commit through the group's deactivate.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False),
            _Frame(dragged=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _full_picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)
        assert fired == []  # dragging fires nothing

        renderer.render(elem)
        assert [e.value for e in fired] == ["#00FF00"]

    def test_channel_bar_drag_commits_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A channel-bar drag to GREEN (the bar reports it, the picker stays quiet)
        # then release fires exactly one commit through the same group deactivate.
        fake = _FakeImgui(
            _Frame(dragged=_GREEN, active=True, committed=False, channel_drag=True),
            _Frame(dragged=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _full_picker(value="#000000")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = ColorPickerRenderer(WidgetState())

        renderer.render(elem)
        assert fired == []  # dragging fires nothing

        renderer.render(elem)
        assert [e.value for e in fired] == ["#00FF00"]
