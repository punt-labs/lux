"""What the dock bar paints, and which clicks it is entitled to act on.

The bar draws on ImGui's foreground draw list, which has no window in the
z-order, so it hit-tests the raw mouse position instead of using widgets. That
makes "is this click mine?" a decision the bar takes rather than one ImGui takes
for it, and these tests are where that decision is pinned down. Extracting the
bar out of the render loop is what made them possible: it now takes its ImGui in,
so a fake stands in for the GL context none of this needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, cast, final

from punt_lux.display.dock_bar import DOCK_BAR_HEIGHT, DockBar
from punt_lux.display.replica.frame import Frame

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.display.replica import SceneReplica

_VIEWPORT_W = 800.0
_VIEWPORT_H = 600.0
_CHAR_W = 7.0
_TEXT_H = 13.0


@final
class _Vec:
    """A point, standing in for ``ImVec2`` where only the numbers matter."""

    x: float
    y: float
    __slots__ = ("x", "y")

    def __new__(cls, x: float, y: float) -> Self:
        self = super().__new__(cls)
        self.x = x
        self.y = y
        return self


@final
class _DrawList:
    """Record what was painted, so a test can assert the geometry."""

    rects: list[tuple[float, float, float, float]]
    texts: list[tuple[float, float, str]]
    lines: list[tuple[float, float, float, float]]
    __slots__ = ("lines", "rects", "texts")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.rects = []
        self.texts = []
        self.lines = []
        return self

    def add_rect_filled(
        self, p_min: Any, p_max: Any, _col: int, _rounding: float = 0.0
    ) -> None:
        self.rects.append((p_min.x, p_min.y, p_max.x, p_max.y))

    def add_line(self, p_min: Any, p_max: Any, _col: int, _thickness: float) -> None:
        self.lines.append((p_min.x, p_min.y, p_max.x, p_max.y))

    def add_text(self, pos: Any, _col: int, text: str) -> None:
        self.texts.append((pos.x, pos.y, text))


@final
class _Colors:
    """Theme slots, named by themselves — the bar only passes them through."""

    title_bg = "title_bg"
    border = "border"
    text = "text"
    button = "button"
    button_hovered = "button_hovered"


@final
class _Buttons:
    left = "left"


@final
class _Style:
    @staticmethod
    def color_(name: str) -> str:
        return name


@final
class _Viewport:
    pos = _Vec(0.0, 0.0)
    size = _Vec(_VIEWPORT_W, _VIEWPORT_H)


@final
class _FakeImGui:
    """The slice of ImGui the dock bar touches: a viewport, a mouse, a draw list."""

    Col_ = _Colors
    MouseButton_ = _Buttons

    draw: _DrawList
    _mouse: _Vec
    _clicked: bool
    _item_hovered: bool
    __slots__ = ("_clicked", "_item_hovered", "_mouse", "draw")

    def __new__(
        cls,
        *,
        mouse: _Vec | None = None,
        clicked: bool = False,
        item_hovered: bool = False,
    ) -> Self:
        self = super().__new__(cls)
        self.draw = _DrawList()
        self._mouse = mouse if mouse is not None else _Vec(-1.0, -1.0)
        self._clicked = clicked
        self._item_hovered = item_hovered
        return self

    def get_main_viewport(self) -> type[_Viewport]:
        return _Viewport

    def get_foreground_draw_list(self) -> _DrawList:
        return self.draw

    def get_style(self) -> type[_Style]:
        return _Style

    def get_color_u32(self, name: str) -> int:
        return hash(name)

    def calc_text_size(self, text: str) -> _Vec:
        """Report a width proportional to the text, which is all layout needs."""
        return _Vec(len(text) * _CHAR_W, _TEXT_H)

    def get_mouse_pos(self) -> _Vec:
        return self._mouse

    def is_mouse_clicked(self, _button: str) -> bool:
        return self._clicked

    def is_any_item_hovered(self) -> bool:
        return self._item_hovered


@final
class _FakeScenes:
    """The two members of SceneReplica the dock bar uses."""

    frames: dict[str, Frame]
    focused: list[str]
    __slots__ = ("focused", "frames")

    def __new__(cls, frames: Mapping[str, Frame]) -> Self:
        self = super().__new__(cls)
        self.frames = dict(frames)
        self.focused = []
        return self

    def request_focus(self, frame_id: str) -> None:
        self.focused.append(frame_id)


def _frame(frame_id: str, title: str, *, minimized: bool) -> Frame:
    return Frame(
        frame_id=frame_id,
        title=title,
        owner_fds=set(),
        scenes={},
        scene_order=[],
        minimized=minimized,
    )


def _bar(scenes: _FakeScenes, imgui: _FakeImGui) -> DockBar:
    return DockBar(imgui, cast("SceneReplica", scenes))


def test_nothing_is_painted_when_no_frame_is_minimized() -> None:
    """An empty bar is no bar — it must not eat the bottom of the viewport."""
    imgui = _FakeImGui()
    scenes = _FakeScenes({"f1": _frame("f1", "Board", minimized=False)})
    _bar(scenes, imgui).render(any_frame_hovered=False)

    assert imgui.draw.rects == []
    assert imgui.draw.texts == []


def test_the_bar_spans_the_viewport_along_its_bottom_edge() -> None:
    """The chrome sits flush to the bottom and runs the full width."""
    imgui = _FakeImGui()
    scenes = _FakeScenes({"f1": _frame("f1", "Board", minimized=True)})
    _bar(scenes, imgui).render(any_frame_hovered=False)

    chrome = imgui.draw.rects[0]
    left, top, right, bottom = chrome
    assert left == 0.0
    assert right == _VIEWPORT_W
    assert bottom == _VIEWPORT_H
    assert bottom - top == DOCK_BAR_HEIGHT


def test_each_pill_sits_inside_the_bar_and_pills_do_not_overlap() -> None:
    """Two pills lie side by side within the strip, in frame order."""
    imgui = _FakeImGui()
    scenes = _FakeScenes(
        {
            "f1": _frame("f1", "First", minimized=True),
            "f2": _frame("f2", "Second", minimized=True),
        }
    )
    _bar(scenes, imgui).render(any_frame_hovered=False)

    bar_top = _VIEWPORT_H - DOCK_BAR_HEIGHT
    first, second = imgui.draw.rects[1], imgui.draw.rects[2]
    assert first[2] <= second[0], "pills overlap"
    for pill in (first, second):
        assert pill[1] > bar_top, "pill escapes the top of the bar"
        assert pill[3] < _VIEWPORT_H, "pill escapes the bottom of the bar"
    assert [text for _, _, text in imgui.draw.texts] == ["First", "Second"]


def test_clicking_a_pill_restores_its_frame_and_asks_for_focus() -> None:
    """The pill under the mouse is the frame that comes back."""
    on_pill = _Vec(20.0, _VIEWPORT_H - DOCK_BAR_HEIGHT / 2)
    imgui = _FakeImGui(mouse=on_pill, clicked=True)
    frame = _frame("f1", "Board", minimized=True)
    scenes = _FakeScenes({"f1": frame})
    _bar(scenes, imgui).render(any_frame_hovered=False)

    assert not frame.minimized
    assert scenes.focused == ["f1"]


def test_a_click_over_a_visible_frame_leaves_the_pill_alone() -> None:
    """A frame overlapping the bar owns the click, so no frame is restored.

    Without this the user clicking inside a window that happens to sit over the
    bar would restore some unrelated frame out from under the click.
    """
    on_pill = _Vec(20.0, _VIEWPORT_H - DOCK_BAR_HEIGHT / 2)
    imgui = _FakeImGui(mouse=on_pill, clicked=True)
    frame = _frame("f1", "Board", minimized=True)
    scenes = _FakeScenes({"f1": frame})
    _bar(scenes, imgui).render(any_frame_hovered=True)

    assert frame.minimized
    assert scenes.focused == []


def test_a_click_on_an_imgui_widget_leaves_the_pill_alone() -> None:
    """An ImGui item under the cursor owns the click before the bar does."""
    on_pill = _Vec(20.0, _VIEWPORT_H - DOCK_BAR_HEIGHT / 2)
    imgui = _FakeImGui(mouse=on_pill, clicked=True, item_hovered=True)
    frame = _frame("f1", "Board", minimized=True)
    scenes = _FakeScenes({"f1": frame})
    _bar(scenes, imgui).render(any_frame_hovered=False)

    assert frame.minimized
    assert scenes.focused == []


def test_pills_that_run_out_of_room_end_in_an_ellipsis() -> None:
    """The row stops at the viewport edge rather than painting off-screen."""
    imgui = _FakeImGui()
    wide = "W" * 40
    scenes = _FakeScenes(
        {f"f{i}": _frame(f"f{i}", f"{wide}{i}", minimized=True) for i in range(8)}
    )
    _bar(scenes, imgui).render(any_frame_hovered=False)

    painted = [text for _, _, text in imgui.draw.texts]
    assert painted[-1] == "..."
    assert len(painted) < 8, "every pill was painted despite running out of room"
    for x, _, _ in imgui.draw.texts:
        assert x < _VIEWPORT_W, "text painted past the right edge"
