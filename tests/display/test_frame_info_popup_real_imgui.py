"""The frame-info glyph's click opens a popup that survives a real mouse press.

Driven through a REAL headless ImGui context and the production
``RenderLoop._render_scene`` -- not a recording stub -- because the defect this
guards was invisible to one: ImGui itself dismissed the popup. A press on the
glyph also presses the frame's title bar, which starts a window move; while the
move is live ImGui re-focuses the frame every frame, and focusing the frame
closes every popup stacked over it. A popup opened on the press frame therefore
lived exactly one frame. Real clicks hold the button for several frames, so the
popup must open on the *release* of a press that did not drag the window.
The live application shows that dismissal; this headless harness does not, so
these tests pin the release-time behaviour, not the dismissal mechanism.
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
_FOREIGN_POPUP = "foreign_popup"


@final
class _HeadlessDisplay:
    """A production ``RenderLoop`` painting one frame into a real ImGui context."""

    _server: RenderLoop
    _frames_run: int
    _foreground_vertices: int
    # Where an unrelated popup (a combo dropdown, a dialog) is pinned, if open.
    _foreign_popup_pos: tuple[float, float] | None
    __slots__ = (
        "_foreground_vertices",
        "_foreign_popup_pos",
        "_frames_run",
        "_server",
    )

    def __new__(cls, facts: tuple[tuple[str, str], ...] = (("Client", "lux"),)) -> Self:
        self = super().__new__(cls)
        imgui.create_context()
        io = imgui.get_io()
        io.set_ini_filename(None)  # a saved layout would leak between runs
        io.display_size = imgui.ImVec2(*_DISPLAY)
        io.config_flags |= imgui.ConfigFlags_.docking_enable.value
        io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
        self._server = RenderLoop("/tmp/test-lux-frame-info-real.sock")
        self._frames_run = 0
        self._foreground_vertices = 0
        self._foreign_popup_pos = None
        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hi")],
            frame_id=_FRAME_ID,
            frame_owner_facts=facts,
        )
        self._server._wrap_abc_elements(msg)
        self._server._scenes.handle_framed_scene(msg, owner_fd=1)
        self.frames(3)  # let ImGui place and size the frame window
        return self

    def close(self) -> None:
        """Tear the ImGui context down."""
        imgui.destroy_context()

    def add_frame(
        self, frame_id: str, frame_flags: dict[str, bool] | None = None
    ) -> None:
        """Replicate a second one-scene frame, as a second agent's would arrive."""
        msg = SceneMessage(
            frame_flags=frame_flags,
            id=f"scene-{frame_id}",
            elements=[TextElement(id=f"text-{frame_id}", content="Hi")],
            frame_id=frame_id,
            frame_owner_facts=(("Client", frame_id),),
        )
        self._server._wrap_abc_elements(msg)
        self._server._scenes.handle_framed_scene(msg, owner_fd=1)
        self.frames(3)  # let ImGui place and size the new window

    @property
    def popup_is_open(self) -> bool:
        """Whether the popup believes itself open."""
        return self._server._frame_info_button.popup.is_open

    @property
    def popup_frame_id(self) -> str:
        """The id of the frame the open popup belongs to."""
        opened = self._server._frame_info_button.popup.open_frame
        assert opened is not None
        return opened.frame_id

    def _window_name(self, frame_id: str) -> str:
        """The ImGui window name of the on-screen frame ``frame_id``."""
        frame = next(
            f for f in self._server._scenes.on_screen_frames() if f.frame_id == frame_id
        )
        addressing = self._server._addressing
        return f"{addressing.frame_title(frame)}##{addressing.frame_window_id(frame)}"

    @property
    def hovered_window_is_popup(self) -> bool:
        """Whether the topmost window under the mouse is an ImGui popup."""
        hovered = imgui.get_current_context().hovered_window
        # pybind yields None when nothing is hovered, though the stub says Window.
        return bool(hovered) and hovered.name.startswith("##Popup")

    @property
    def popup_width(self) -> float:
        """The open popup window's current width."""
        windows = imgui.get_current_context().windows
        return next(w for w in windows if w.name.startswith("##Popup")).size.x

    def _popup_window(self) -> imgui.internal.Window:
        """The open popup's ImGui window."""
        windows = imgui.get_current_context().windows
        return next(w for w in windows if w.name.startswith("##Popup"))

    @property
    def popup_content_right(self) -> float:
        """The popup's right content edge: its right edge less the window padding."""
        window = self._popup_window()
        return window.pos.x + window.size.x - imgui.get_style().window_padding.x

    def _hover_span(self, *, along_x: bool, fixed: float) -> tuple[float, float]:
        """The (low, high) screen coordinate where the close button is hovered.

        The button is an ImGui item with no rect the test can read back, so the
        mouse sweeps a line across the popup (a quarter pixel at a time) and the
        span is where ImGui says the button, and nothing else, is hovered.
        """
        window = self._popup_window()
        button_id = window.get_id("##close")
        start = window.pos.x if along_x else window.pos.y
        extent = window.size.x if along_x else window.size.y
        hits = []
        offset = 0.0
        while offset < extent:
            at = start + offset
            self.move_mouse((at, fixed) if along_x else (fixed, at))
            self.frames(1)
            if imgui.get_current_context().hovered_id == button_id:
                hits.append(at)
            offset += 0.25
        return min(hits), max(hits) + 0.25

    def close_button_span(self) -> tuple[float, float]:
        """The close button's (left, right) screen x."""
        window = self._popup_window()
        return self._hover_span(
            along_x=True, fixed=window.pos.y + imgui.get_style().window_padding.y + 4.0
        )

    def close_button_centre_y(self) -> float:
        """The close button's vertical centre on screen."""
        left, right = self.close_button_span()
        top, bottom = self._hover_span(along_x=False, fixed=(left + right) / 2)
        return (top + bottom) / 2

    @property
    def title_line_centre_y(self) -> float:
        """The vertical centre of the popup's "Connection" title line."""
        window = self._popup_window()
        top = window.pos.y + imgui.get_style().window_padding.y
        return top + imgui.get_text_line_height() / 2

    def click_close_button(self) -> None:
        """Press and release the left button on the close button's centre."""
        left, right = self.close_button_span()
        self.move_mouse(((left + right) / 2, self.close_button_centre_y()))
        self.frames(1)
        self.press()
        self.frames(2)
        self.release()
        self.frames(3)

    @property
    def title_right(self) -> float:
        """The right edge of the popup's "Connection" title."""
        window = self._popup_window()
        title = imgui.calc_text_size("Connection").x
        return window.pos.x + imgui.get_style().window_padding.x + title

    @property
    def foreground_vertex_count(self) -> int:
        """Vertices on the global foreground draw list in the last rendered frame."""
        return self._foreground_vertices

    def frames(self, count: int) -> None:
        """Run ``count`` full render passes."""
        for _ in range(count):
            imgui.get_io().delta_time = 1 / 60
            imgui.new_frame()
            self._server._render_scene()
            self._render_foreign_popup()
            self._foreground_vertices = len(imgui.get_foreground_draw_list().vtx_buffer)
            imgui.render()
            self._frames_run += 1

    def open_foreign_popup_at(self, pos: tuple[float, float]) -> None:
        """Open a popup unrelated to the info popup, pinned at ``pos``."""
        self._foreign_popup_pos = pos
        imgui.get_io().delta_time = 1 / 60
        imgui.new_frame()
        self._server._render_scene()
        imgui.open_popup(_FOREIGN_POPUP)
        self._render_foreign_popup()
        imgui.render()
        self._frames_run += 1
        self.frames(3)  # let it place and take focus

    def _render_foreign_popup(self) -> None:
        """Draw the unrelated popup, when one is open, at the root ID scope."""
        if self._foreign_popup_pos is None:
            return
        imgui.set_next_window_pos(imgui.ImVec2(*self._foreign_popup_pos))
        if imgui.begin_popup(_FOREIGN_POPUP):
            imgui.dummy(imgui.ImVec2(200.0, 120.0))
            imgui.end_popup()

    def move_frame_to(
        self, pos: tuple[float, float], frame_id: str = _FRAME_ID
    ) -> None:
        """Teleport the frame window, as a resize, Fit All, or raise would."""
        name = self._window_name(frame_id)
        imgui.get_io().delta_time = 1 / 60
        imgui.new_frame()
        imgui.set_window_pos(name, imgui.ImVec2(*pos))
        self._server._render_scene()
        imgui.render()
        self._frames_run += 1
        self.frames(3)  # let the move settle before the next click

    def glyph_centre(self, frame_id: str = _FRAME_ID) -> tuple[float, float]:
        """The title-bar glyph's centre, derived from the live window rect."""
        window = imgui.internal.find_window_by_name(self._window_name(frame_id))
        band = imgui.get_frame_height()
        glyph = band * 0.625
        high_x = window.pos.x + window.size.x - band - 4.0
        high_y = window.pos.y + (band + glyph) / 2
        return high_x - glyph / 2, high_y - glyph / 2

    def put_glyph_at(self, frame_id: str, spot: tuple[float, float]) -> None:
        """Teleport ``frame_id`` so its glyph's centre is at ``spot``."""
        self.move_frame_to((0.0, 0.0), frame_id)
        home_x, home_y = self.glyph_centre(frame_id)
        self.move_frame_to((spot[0] - home_x, spot[1] - home_y), frame_id)

    def click_at(self, spot: tuple[float, float]) -> None:
        """Press, hold, and release the left button at ``spot``."""
        self.move_mouse(spot)
        self.frames(1)
        self.press()
        self.frames(3)
        self.release()
        self.frames(1)

    def move_mouse(self, pos: tuple[float, float]) -> None:
        """Queue a mouse move."""
        imgui.get_io().add_mouse_pos_event(*pos)

    def press(self) -> None:
        """Queue a left-button press."""
        imgui.get_io().add_mouse_button_event(_LEFT, True)

    def release(self) -> None:
        """Queue a left-button release."""
        imgui.get_io().add_mouse_button_event(_LEFT, False)

    def click_glyph(self, *, held_frames: int, frame_id: str = _FRAME_ID) -> None:
        """Press the glyph, hold ``held_frames`` frames, release, settle."""
        self.move_mouse(self.glyph_centre(frame_id))
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


def _reopen_beside_the_glyph(display: _HeadlessDisplay) -> None:
    """Open the popup, then move the frame so its glyph is no longer under it.

    A press on the glyph is then a press outside the popup, which ImGui shuts.
    """
    display.click_glyph(held_frames=3)
    display.frames(4)
    assert display.popup_is_open
    display.move_frame_to((500.0, 500.0))
    display.move_mouse(display.glyph_centre())
    display.frames(1)


def test_imgui_shuts_the_popup_at_the_end_of_the_press_frame_not_during_it(
    display: _HeadlessDisplay,
) -> None:
    """The code is told a frame late: the glyph's press still finds it open.

    This is the premise of the press record -- a glyph reading the popup at the
    press sees it open on the frame ImGui shuts it, and by the release it is
    closed -- so a change in ImGui's timing must fail here, loudly.
    """
    _reopen_beside_the_glyph(display)

    display.press()
    display.frames(1)
    assert display.popup_is_open

    display.frames(1)
    assert not display.popup_is_open


def test_a_second_click_released_on_the_frame_after_the_press_closes_the_popup(
    display: _HeadlessDisplay,
) -> None:
    """The release finds the popup still open on the code's side: it closes it."""
    _reopen_beside_the_glyph(display)

    display.press()
    display.frames(1)
    display.release()
    display.frames(1)
    display.frames(3)

    assert not display.popup_is_open


def test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup(
    display: _HeadlessDisplay,
) -> None:
    """By the release the code has seen ImGui shut the popup: nothing to toggle."""
    _reopen_beside_the_glyph(display)

    display.press()
    display.frames(2)
    display.release()
    display.frames(3)

    assert not display.popup_is_open


def test_a_click_on_another_frames_glyph_moves_the_popup_to_it(
    display: _HeadlessDisplay,
) -> None:
    display.add_frame("f2")
    display.move_frame_to((200.0, 300.0), "f2")
    display.click_glyph(held_frames=3)
    display.frames(4)
    assert display.popup_frame_id == _FRAME_ID

    display.click_glyph(held_frames=3, frame_id="f2")
    display.frames(4)

    assert display.popup_is_open
    assert display.popup_frame_id == "f2"


def test_a_click_on_a_glyph_under_an_unrelated_popup_does_not_open_the_info_popup(
    display: _HeadlessDisplay,
) -> None:
    """A dialog or combo dropdown over a glyph owns the click, not the glyph."""
    x, y = display.glyph_centre()
    display.open_foreign_popup_at((x - 20.0, y - 20.0))

    display.click_glyph(held_frames=3)
    display.frames(4)

    assert not display.popup_is_open


def test_a_click_on_the_info_popup_over_another_frames_glyph_leaves_the_popup(
    display: _HeadlessDisplay,
) -> None:
    """The popup is in front of the buried glyph: the click is the popup's."""
    display.add_frame("f2")
    display.move_frame_to((200.0, 300.0), "f2")
    display.click_glyph(held_frames=3)
    display.frames(4)
    assert display.popup_frame_id == _FRAME_ID
    ax, ay = display.glyph_centre()
    display.put_glyph_at("f2", (ax + 60.0, ay + 20.0))

    display.click_at((ax + 60.0, ay + 20.0))
    display.frames(4)

    assert display.popup_frame_id == _FRAME_ID


def test_dragging_away_and_back_over_an_open_popup_neither_closes_nor_reopens_it(
    display: _HeadlessDisplay,
) -> None:
    """A press that travelled is a window move: it toggles the popup neither way."""
    display.click_glyph(held_frames=3)
    display.frames(4)
    assert display.popup_is_open
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

    assert display.popup_is_open


def _cover_glyph_with_second_frame(display: _HeadlessDisplay) -> tuple[float, float]:
    """Put a second, front frame over the first frame's glyph; return that spot."""
    display.add_frame("f2")
    x, y = display.glyph_centre()
    display.move_frame_to((x - 60.0, y - 60.0), "f2")
    return x, y


def test_a_click_on_a_glyph_hidden_under_a_front_frame_does_not_open_its_popup(
    display: _HeadlessDisplay,
) -> None:
    _cover_glyph_with_second_frame(display)

    display.click_glyph(held_frames=3)
    display.frames(4)

    assert not display.popup_is_open


def test_the_glyph_paints_on_its_own_window_so_a_front_frame_covers_it(
    display: _HeadlessDisplay,
) -> None:
    """Only a window's own draw list obeys z-order; the global foreground list
    would draw a hidden frame's glyph on top of whatever is in front."""
    _cover_glyph_with_second_frame(display)
    display.frames(2)

    assert display.foreground_vertex_count == 0


def test_a_frame_without_a_title_bar_has_no_glyph_to_click(
    display: _HeadlessDisplay,
) -> None:
    """With no title bar there is nothing to host the glyph: it would paint over
    the content and its hit test would intercept clicks meant for it."""
    display.add_frame("f2", {"no_title_bar": True})

    display.click_glyph(held_frames=3, frame_id="f2")
    display.frames(4)

    assert not display.popup_is_open


def test_the_open_popup_keeps_one_width_across_frames(
    display: _HeadlessDisplay,
) -> None:
    """A close button placed from leftover width would feed the popup's own
    auto-sized width back into the layout and make it breathe frame to frame."""
    display.click_glyph(held_frames=3)
    display.frames(4)
    assert display.popup_is_open

    widths = []
    for _ in range(6):
        display.frames(1)
        widths.append(display.popup_width)

    assert len(set(widths)) == 1


_LONG_FACTS = (
    ("Client", "claude-code-session-with-a-long-name"),
    ("Hub", "hub-0123456789abcdef0123456789abcdef"),
    ("Connection", "unix:///home/someone/.punt-labs/lux/run/display.sock"),
    ("Kind", "agent"),
)


def _open_popup(facts: tuple[tuple[str, str], ...]) -> _HeadlessDisplay:
    shown = _HeadlessDisplay(facts)
    shown.click_glyph(held_frames=3)
    shown.frames(4)
    assert shown.popup_is_open
    return shown


def test_the_close_button_sits_in_the_popups_top_right_corner() -> None:
    display = _open_popup(_LONG_FACTS)
    try:
        _, right = display.close_button_span()
        assert abs(right - display.popup_content_right) <= 2.0
    finally:
        display.close()


def test_the_popup_width_is_identical_across_consecutive_frames_with_long_rows() -> (
    None
):
    display = _open_popup(_LONG_FACTS)
    try:
        widths = []
        for _ in range(8):
            display.frames(1)
            widths.append(display.popup_width)
        assert len(set(widths)) == 1
    finally:
        display.close()


def test_the_close_button_does_not_overlap_the_title() -> None:
    display = _open_popup(_LONG_FACTS)
    try:
        left, _ = display.close_button_span()
        assert left > display.title_right
    finally:
        display.close()


def test_a_title_wider_than_the_rows_still_keeps_the_button_clear_of_it() -> None:
    display = _open_popup((("A", "b"),))
    try:
        left, _ = display.close_button_span()
        assert left > display.title_right
    finally:
        display.close()


def test_a_title_wider_than_the_rows_keeps_one_width_across_frames() -> None:
    display = _open_popup((("A", "b"),))
    try:
        widths = []
        for _ in range(8):
            display.frames(1)
            widths.append(display.popup_width)
        assert len(set(widths)) == 1
    finally:
        display.close()


def test_the_close_button_is_vertically_centred_on_the_title_line() -> None:
    display = _open_popup(_LONG_FACTS)
    try:
        centre = display.close_button_centre_y()
        assert abs(centre - display.title_line_centre_y) <= 0.5
    finally:
        display.close()


def test_clicking_the_close_button_closes_the_popup() -> None:
    display = _open_popup(_LONG_FACTS)
    try:
        display.click_close_button()
        assert not display.popup_is_open
    finally:
        display.close()
