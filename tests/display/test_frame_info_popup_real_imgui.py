"""The frame-info glyph's click opens a popup that survives a real mouse press.

Driven through a REAL headless ImGui context and the production
``RenderLoop._render_scene`` -- not a recording stub -- because the defect this
guards was invisible to one: ImGui itself dismissed the popup. A press on the
glyph also presses the frame's title bar, which starts a window move; while the
move is live ImGui re-focuses the frame every frame, and focusing the frame
closes every popup stacked over it. A popup opened on the press frame therefore
lived exactly one frame. Real clicks hold the button for several frames, so the
popup must open on the *release* of a press that did not drag the window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

import pytest
from imgui_bundle import imgui

from punt_lux.display import RenderLoop
from punt_lux.protocol import SceneMessage, TextElement

if TYPE_CHECKING:
    from collections.abc import Iterator

_DISPLAY = (1000.0, 800.0)
_FRAME_ID = "f1"
_LEFT = 0


@final
class _HeadlessDisplay:
    """A production ``RenderLoop`` painting one frame into a real ImGui context."""

    _server: RenderLoop
    _frames_run: int
    __slots__ = ("_frames_run", "_server")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        imgui.create_context()
        io = imgui.get_io()
        io.set_ini_filename(None)  # a saved layout would leak between runs
        io.display_size = imgui.ImVec2(*_DISPLAY)
        io.config_flags |= imgui.ConfigFlags_.docking_enable.value
        io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
        self._server = RenderLoop("/tmp/test-lux-frame-info-real.sock")
        self._frames_run = 0
        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hi")],
            frame_id=_FRAME_ID,
            frame_owner_facts=(("Client", "lux"),),
        )
        self._server._wrap_abc_elements(msg)
        self._server._scenes.handle_framed_scene(msg, owner_fd=1)
        self.frames(3)  # let ImGui place and size the frame window
        return self

    def close(self) -> None:
        """Tear the ImGui context down."""
        imgui.destroy_context()

    @property
    def popup_is_open(self) -> bool:
        """Whether the popup believes itself open."""
        return self._server._frame_info_button.popup.is_open

    @property
    def hovered_window_is_popup(self) -> bool:
        """Whether the topmost window under the mouse is an ImGui popup."""
        hovered = imgui.get_current_context().hovered_window
        # pybind yields None when nothing is hovered, though the stub says Window.
        return bool(hovered) and hovered.name.startswith("##Popup")

    def frames(self, count: int) -> None:
        """Run ``count`` full render passes."""
        for _ in range(count):
            imgui.get_io().delta_time = 1 / 60
            imgui.new_frame()
            self._server._render_scene()
            imgui.render()
            self._frames_run += 1

    def move_frame_to(self, pos: tuple[float, float]) -> None:
        """Teleport the frame window, as a resize, Fit All, or raise would."""
        frame = self._server._scenes.on_screen_frames()[0]
        addressing = self._server._addressing
        name = f"{addressing.frame_title(frame)}##{addressing.frame_window_id(frame)}"
        imgui.get_io().delta_time = 1 / 60
        imgui.new_frame()
        imgui.set_window_pos(name, imgui.ImVec2(*pos))
        self._server._render_scene()
        imgui.render()
        self._frames_run += 1
        self.frames(3)  # let the move settle before the next click

    def glyph_centre(self) -> tuple[float, float]:
        """The title-bar glyph's centre, derived from the live window rect."""
        frame = self._server._scenes.on_screen_frames()[0]
        addressing = self._server._addressing
        name = f"{addressing.frame_title(frame)}##{addressing.frame_window_id(frame)}"
        window = imgui.internal.find_window_by_name(name)
        band = imgui.get_frame_height()
        glyph = band * 0.625
        high_x = window.pos.x + window.size.x - band - 4.0
        high_y = window.pos.y + (band + glyph) / 2
        return high_x - glyph / 2, high_y - glyph / 2

    def move_mouse(self, pos: tuple[float, float]) -> None:
        """Queue a mouse move."""
        imgui.get_io().add_mouse_pos_event(*pos)

    def press(self) -> None:
        """Queue a left-button press."""
        imgui.get_io().add_mouse_button_event(_LEFT, True)

    def release(self) -> None:
        """Queue a left-button release."""
        imgui.get_io().add_mouse_button_event(_LEFT, False)

    def click_glyph(self, *, held_frames: int) -> None:
        """Press the glyph, hold ``held_frames`` frames, release, settle."""
        self.move_mouse(self.glyph_centre())
        self.frames(1)
        self.press()
        self.frames(held_frames)
        self.release()
        self.frames(1)

    def near_miss_click(self) -> None:
        """Press just outside the glyph, ease inside it, and release there.

        The press lands on the title bar a hair off the glyph and travels less
        than the drag threshold, so it is no window move -- yet it never began
        on the glyph, and a release over the glyph must not count as its click.
        """
        x, y = self.glyph_centre()
        half = imgui.get_frame_height() * 0.625 / 2
        self.move_mouse((x + half + 1.5, y))
        self.frames(1)
        self.press()
        self.frames(2)
        self.move_mouse((x + half - 1.0, y))
        self.frames(2)
        self.release()
        self.frames(1)


@pytest.fixture
def display() -> Iterator[_HeadlessDisplay]:
    shown = _HeadlessDisplay()
    try:
        yield shown
    finally:
        shown.close()


@pytest.mark.parametrize("held_frames", [1, 2, 3, 8])
def test_a_real_click_leaves_the_popup_open(
    display: _HeadlessDisplay, held_frames: int
) -> None:
    display.click_glyph(held_frames=held_frames)
    display.frames(4)

    assert display.popup_is_open


def test_the_popup_sits_above_the_frame_that_spawned_it(
    display: _HeadlessDisplay,
) -> None:
    display.click_glyph(held_frames=3)
    display.frames(4)

    assert display.hovered_window_is_popup


def test_a_second_click_on_the_glyph_closes_the_popup(
    display: _HeadlessDisplay,
) -> None:
    display.click_glyph(held_frames=3)
    display.frames(4)

    display.click_glyph(held_frames=3)
    display.frames(4)

    assert not display.popup_is_open


def test_dragging_the_frame_by_the_glyph_does_not_open_the_popup(
    display: _HeadlessDisplay,
) -> None:
    x, y = display.glyph_centre()
    display.move_mouse((x, y))
    display.frames(1)
    display.press()
    display.frames(2)
    display.move_mouse((x - 120.0, y + 90.0))
    display.frames(2)
    display.release()
    display.frames(4)

    assert not display.popup_is_open


def test_dragging_away_and_back_before_releasing_does_not_open_the_popup(
    display: _HeadlessDisplay,
) -> None:
    """A press that travelled is a window move even if it ends where it began."""
    x, y = display.glyph_centre()
    display.move_mouse((x, y))
    display.frames(1)
    display.press()
    display.frames(2)
    display.move_mouse((x + 40.0, y + 30.0))
    display.frames(2)
    display.move_mouse((x, y))
    display.frames(2)
    display.release()
    display.frames(4)

    assert not display.popup_is_open


def test_a_second_click_closes_a_popup_that_does_not_cover_the_glyph(
    display: _HeadlessDisplay,
) -> None:
    """The popup is anchored where the glyph was; once the frame moves away the
    second press lands outside the popup, so ImGui itself shuts it on the press.
    The release must read that as a toggle-close, not reopen what it just shut."""
    display.click_glyph(held_frames=3)
    display.frames(4)
    assert display.popup_is_open
    display.move_frame_to((500.0, 500.0))

    display.click_glyph(held_frames=3)
    display.frames(4)

    assert not display.popup_is_open


def test_a_release_on_the_glyph_whose_press_began_beside_it_does_not_open(
    display: _HeadlessDisplay,
) -> None:
    display.near_miss_click()
    display.frames(4)

    assert not display.popup_is_open


def test_a_proper_click_opens_the_popup_after_a_near_miss(
    display: _HeadlessDisplay,
) -> None:
    display.near_miss_click()
    display.frames(4)

    display.click_glyph(held_frames=3)
    display.frames(4)

    assert display.popup_is_open
