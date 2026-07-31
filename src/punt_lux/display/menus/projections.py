"""The two surfaces that show the menu: the menu bar and the World panel.

Both take the same :class:`MenuModel` and render it. Neither builds entries of
its own, so the bar and the World panel cannot drift apart: a menu added to the
model appears on both, and a click on a leaf produces the same invocation
whichever surface it came from.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.display.menus.model import MenuModel
    from punt_lux.scene.frame import Frame

__all__ = ["MenuBar", "WorldPanel"]

# Distinguishes the World panel's ImGui ids from the menu bar's when both render
# the same menu in one frame.
_WORLD_ID_SUFFIX = "##world"

# Height of the dock bar the server paints for minimized frames. The dock bar is
# emitted after the World panel's hit test, so its region is rejected by hand.
_DOCK_BAR_HEIGHT = 28.0

_PANEL_WIDTH = 220.0


@final
class MenuBar:
    """Show the menu model as the application menu bar."""

    __slots__ = ()

    def render(self, imgui: Any, model: MenuModel) -> None:
        """Render every menu in the model as a top-level bar menu."""
        model.render(imgui)


@final
class WorldPanel:
    """Show the menu model in a floating panel, opened by a background click.

    The panel is the Pharo-style World menu: the same menus as the bar, brought
    to where the user clicked instead of to the top of the screen.
    """

    _get_frames: Callable[[], Mapping[str, Frame]]
    _open: bool
    _pinned: bool
    _spawn_pos: tuple[float, float]
    _placed: bool
    __slots__ = ("_get_frames", "_open", "_pinned", "_placed", "_spawn_pos")

    def __new__(cls, get_frames: Callable[[], Mapping[str, Frame]]) -> Self:
        self = super().__new__(cls)
        self._get_frames = get_frames
        self._open = False
        self._pinned = False
        self._spawn_pos = (0.0, 0.0)
        self._placed = True
        return self

    @property
    def is_open(self) -> bool:
        """Return whether the panel is currently showing."""
        return self._open

    def check_background_click(self, imgui: Any) -> None:
        """Toggle the panel on a left click on the main window background.

        ``is_window_hovered()`` with no flags asks about the *current* window,
        which at this point in the render loop is the main window. A frame or
        the panel itself lying over the click makes that False, so clicks on
        content never reach here. The dock bar is the exception: it is painted
        later in the frame, so ImGui does not know it is hovered yet and its
        region is rejected explicitly.
        """
        if not imgui.is_mouse_clicked(imgui.MouseButton_.left):
            return
        if imgui.is_any_item_hovered():
            return
        if not imgui.is_window_hovered():
            return
        if self._over_dock_bar(imgui):
            return
        self._open = not self._open
        if self._open:
            pos = imgui.get_mouse_pos()
            self._spawn_pos = (pos.x, pos.y)
            self._placed = False

    def render(self, imgui: Any, model: MenuModel) -> None:
        """Render the panel over the background while it is open."""
        if not self._open:
            return
        self._place(imgui)
        wants_open = True  # ImGui writes the close-button's answer back into this
        _, still_open = imgui.begin(
            "World###world_panel", wants_open, self._flags(imgui)
        )
        if not still_open:
            self._close()
            imgui.end()
            return
        self._render_pin(imgui)
        imgui.separator()
        activated = model.render(imgui, _WORLD_ID_SUFFIX)
        imgui.end()
        if activated and not self._pinned:
            self._open = False

    def _over_dock_bar(self, imgui: Any) -> bool:
        """Return whether the mouse is over the dock bar's strip of the viewport."""
        if not any(frame.minimized for frame in self._get_frames().values()):
            return False
        viewport = imgui.get_main_viewport()
        bar_top = viewport.pos.y + viewport.size.y - _DOCK_BAR_HEIGHT
        return bool(imgui.get_mouse_pos().y >= bar_top)

    def _place(self, imgui: Any) -> None:
        """Size the panel, and put it where the click landed the first frame."""
        imgui.set_next_window_size((_PANEL_WIDTH, 0), imgui.Cond_.first_use_ever.value)
        if self._placed:
            return
        imgui.set_next_window_pos(self._spawn_pos, imgui.Cond_.always.value)
        self._placed = True

    def _render_pin(self, imgui: Any) -> None:
        """Render the pin dot — filled when pinned, hollow when not."""
        dot = "●" if self._pinned else "○"
        if imgui.small_button(f"{dot}##pin"):
            self._pinned = not self._pinned

    def _close(self) -> None:
        """Close the panel and drop its pin."""
        self._open = False
        self._pinned = False

    @staticmethod
    def _flags(imgui: Any) -> int:
        """Return the window flags: no collapse arrow, sized to its contents."""
        return int(
            imgui.WindowFlags_.no_collapse.value
            | imgui.WindowFlags_.always_auto_resize.value
        )
