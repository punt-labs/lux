"""The title-bar info button: drawn on an expanded frame only, opens the popup.

Painted on the foreground draw list and hit-tested by raw mouse position --
a title bar sits outside a window's content-area clip rect, so a normal
ImGui item there (``small_button`` included) is silently culled before it
ever draws or can be clicked. Mirrors ``test_dock_bar.py``'s fake for the
identical reason (``DockPill``'s draw-list-plus-manual-hit-test pattern).

Extends the ``_render_single_frame`` fixture from
``tests/test_frame_geometry_timing.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Self

from punt_lux.display import RenderLoop
from punt_lux.display.frame_placement import FramePlacement
from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.display.replica.frame import Frame
from punt_lux.domain.identity import HubId
from punt_lux.protocol import SceneMessage, TextElement

if TYPE_CHECKING:
    import pytest

_DEFAULT_SIZE = (800.0, 600.0)
_PLACEMENT = FramePlacement(fitting=False, tile_layout={}, default_size=_DEFAULT_SIZE)

# Matches _render_single_frame's window geometry below: pos (100, 100),
# size (400, 300), a 20-tall title bar, FrameInfoButton's own 4.0 gap from
# the native close x, and its 0.625 scale -- the button's rect is
# [(463.5, 103.75), (476.0, 116.25)].
_ON_BUTTON = (470.0, 110.0)
_OFF_BUTTON = (0.0, 0.0)
_EXPECTED_ANCHOR = (463.5, 103.75)


def _make_server() -> RenderLoop:
    return RenderLoop("/tmp/test-lux-frame-info-button.sock")


def _frame() -> Frame:
    return Frame(
        hub=HubId.stub(),
        frame_id="f1",
        title="F",
        owner_fds=set(),
        scenes={},
        scene_order=[],
    )


def _adopt_owner_facts(
    server: RenderLoop, rows: tuple[tuple[str, str], ...] | None
) -> None:
    """Seed the server's owner-facts store for frame ``f1`` via the real push path.

    The store lives on ``SceneReplica``, keyed by ``(hub, frame_id)`` -- not
    on ``Frame`` -- so a test that wants the button to find rows pushes a
    scene naming ``f1`` with ``frame_owner_facts``, exactly as a real Hub
    replication would.
    """
    server._scenes.handle_framed_scene(
        SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hi")],
            frame_id="f1",
            frame_owner_facts=rows,
        ),
        owner_fd=1,
    )


class _Vec2:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _DrawList:
    """Record what was painted, so a test can assert the geometry."""

    rects: list[tuple[float, float, float, float]]
    texts: list[tuple[float, float, str]]
    __slots__ = ("rects", "texts")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.rects = []
        self.texts = []
        return self

    def add_rect_filled(
        self, p_min: _Vec2, p_max: _Vec2, _col: int, _rounding: float = 0.0
    ) -> None:
        self.rects.append((p_min.x, p_min.y, p_max.x, p_max.y))

    def add_text(self, pos: _Vec2, _col: int, text: str) -> None:
        self.texts.append((pos.x, pos.y, text))


class _Colors:
    button = "button"
    button_hovered = "button_hovered"
    text = "text"


class _Buttons:
    left = "left"


class _Style:
    @staticmethod
    def color_(name: str) -> str:
        return name


class _FakeImgui:
    """A minimal ImGui stand-in scripting ``begin`` plus the button surface."""

    Cond_ = SimpleNamespace(
        always=SimpleNamespace(value=0), first_use_ever=SimpleNamespace(value=0)
    )
    HoveredFlags_ = SimpleNamespace(root_and_child_windows=SimpleNamespace(value=0))
    Col_ = _Colors
    MouseButton_ = _Buttons

    _expanded: bool
    _clicked: bool
    _mouse: _Vec2
    draw: _DrawList
    __slots__ = ("_clicked", "_expanded", "_mouse", "draw")

    def __new__(
        cls, *, expanded: bool, clicked: bool, mouse: tuple[float, float] = _OFF_BUTTON
    ) -> Self:
        self = super().__new__(cls)
        self._expanded = expanded
        self._clicked = clicked
        self._mouse = _Vec2(*mouse)
        self.draw = _DrawList()
        return self

    def set_next_window_pos(self, _pos: object, _cond: int) -> None: ...

    def set_next_window_size(self, _size: object, _cond: int) -> None: ...

    def begin(self, _title: str, still_open: bool, _flags: int) -> tuple[bool, bool]:
        return self._expanded, still_open

    def is_window_hovered(self, _flags: int) -> bool:
        return False

    def is_window_docked(self) -> bool:
        return False

    def set_window_collapsed(self, _collapsed: bool) -> None: ...

    def end(self) -> None: ...

    def get_window_pos(self) -> _Vec2:
        return _Vec2(100.0, 100.0)

    def get_window_size(self) -> _Vec2:
        return _Vec2(400.0, 300.0)

    def get_frame_height(self) -> float:
        return 20.0

    def get_foreground_draw_list(self) -> _DrawList:
        return self.draw

    def get_style(self) -> type[_Style]:
        return _Style

    def get_color_u32(self, name: str) -> int:
        return hash(name)

    def calc_text_size(self, text: str) -> _Vec2:
        return _Vec2(len(text) * 7.0, 13.0)

    def get_mouse_pos(self) -> _Vec2:
        return self._mouse

    def is_mouse_clicked(self, _button: str) -> bool:
        return self._clicked


def _record_frame_no_op(_self: object, _frame_id: str) -> None:
    """Stand in for ``GeometryCapture.record_frame`` -- see ``_no_op_geometry``."""


def _no_op_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the real-imgui geometry recording every render pass makes.

    ``GeometryCapture.record_frame`` reads the live ``imgui_bundle`` module
    directly rather than the injected fake, so it segfaults outside a real
    GL context -- irrelevant to what these tests exercise (the button).
    """
    monkeypatch.setattr(GeometryCapture, "record_frame", _record_frame_no_op)


def test_the_button_is_drawn_on_an_expanded_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    fake = _FakeImgui(expanded=True, clicked=False)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert fake.draw.rects  # the glyph's background was painted
    assert fake.draw.texts  # and its label


def test_the_button_is_not_drawn_on_a_collapsed_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    fake = _FakeImgui(expanded=False, clicked=False)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert not fake.draw.rects  # collapsed -- no contents, no button
    assert not fake.draw.texts


def test_clicking_the_button_opens_the_popup_at_the_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    rows = (("Client", "lux"),)
    _adopt_owner_facts(server, rows)
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert server._frame_info_popup.is_open
    assert server._frame_info_popup.spawn_pos == _EXPECTED_ANCHOR


def test_a_click_off_the_button_does_not_open_the_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_OFF_BUTTON)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert not server._frame_info_popup.is_open


def test_a_frame_with_no_owner_facts_still_opens_an_explanatory_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An untracked/unresolved owner is never a silent no-op: the popup opens
    with an explicit row rather than staying blank."""
    _no_op_geometry(monkeypatch)
    server = _make_server()
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert server._frame_info_popup.is_open
    assert server._frame_info_popup.rows == (("Owner", "unknown"),)


def test_a_resolved_but_empty_result_is_not_treated_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely resolved, empty row set is distinct from an untracked owner --
    only ``None`` (never adopted) gets the explanatory row."""
    _no_op_geometry(monkeypatch)
    server = _make_server()
    _adopt_owner_facts(server, ())
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert server._frame_info_popup.rows == ()
