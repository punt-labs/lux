"""The title-bar info button: drawn on an expanded frame only, opens the popup.

Extends the ``_render_single_frame`` fixture from
``tests/test_frame_geometry_timing.py`` with the button-facing ImGui surface
(``small_button``, ``get_window_pos``/``get_window_size``/``get_frame_height``,
``set_cursor_screen_pos``, ``get_item_rect_min``).
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

    The store lives on ``SceneReplica``, keyed by frame id -- not on ``Frame``
    -- so a test that wants the button to find rows pushes a scene naming
    ``f1`` with ``frame_owner_facts``, exactly as a real Hub replication would.
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


class _FakeImgui:
    """A minimal ImGui stand-in scripting ``begin`` plus the button surface."""

    _expanded: bool
    _clicked: bool
    _cursor_positions: list[object]
    _button_labels: list[str]
    _item_rect_min: _Vec2
    __slots__ = (
        "_button_labels",
        "_clicked",
        "_cursor_positions",
        "_expanded",
        "_item_rect_min",
    )

    Cond_ = SimpleNamespace(
        always=SimpleNamespace(value=0), first_use_ever=SimpleNamespace(value=0)
    )
    HoveredFlags_ = SimpleNamespace(root_and_child_windows=SimpleNamespace(value=0))

    def __new__(cls, *, expanded: bool, clicked: bool) -> Self:
        self = super().__new__(cls)
        self._expanded = expanded
        self._clicked = clicked
        self._cursor_positions = []
        self._button_labels = []
        self._item_rect_min = _Vec2(370.0, 100.0)
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

    def set_cursor_screen_pos(self, pos: object) -> None:
        self._cursor_positions.append(pos)

    def small_button(self, label: str) -> bool:
        self._button_labels.append(label)
        return self._clicked

    def get_item_rect_min(self) -> _Vec2:
        return self._item_rect_min


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

    assert fake._button_labels  # a button was drawn


def test_the_button_is_not_drawn_on_a_collapsed_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    fake = _FakeImgui(expanded=False, clicked=False)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert not fake._button_labels  # collapsed -- no contents, no button


def test_clicking_the_button_opens_the_popup_at_the_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    rows = (("Client", "lux"),)
    _adopt_owner_facts(server, rows)
    fake = _FakeImgui(expanded=True, clicked=True)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert server._frame_info_popup.is_open


def test_a_frame_with_no_owner_facts_still_opens_an_empty_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_op_geometry(monkeypatch)
    server = _make_server()
    fake = _FakeImgui(expanded=True, clicked=True)

    server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert server._frame_info_popup.is_open
