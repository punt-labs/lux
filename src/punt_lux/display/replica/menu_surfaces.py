"""MenuSurfaces — the two rendering surfaces menu state draws through: the
application menu bar and the World panel, both guarded by the same model
builder.

Composed out of :class:`MenuReplica <punt_lux.display.replica.menu_replica.MenuReplica>`
so the render-surface concern clusters around its own state, separate from
the replicated menu state (:class:`ReplicatedMenus
<punt_lux.display.replica.replicated_menus.ReplicatedMenus>`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus import GuardedMenu, MenuBar, WorldPanel

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.display.menus import MenuModel
    from punt_lux.display.replica.frame import Frame

__all__ = ["MenuSurfaces"]


@final
class MenuSurfaces:
    """Own the two ImGui surfaces menu state draws through."""

    _bar: GuardedMenu
    _panel: WorldPanel
    _world: GuardedMenu
    __slots__ = ("_bar", "_panel", "_world")

    def __new__(
        cls,
        *,
        menu_model: Callable[[], MenuModel],
        get_frames: Callable[[], Mapping[str, Frame]],
    ) -> Self:
        self = super().__new__(cls)
        self._bar = GuardedMenu(MenuBar(), menu_model)
        self._panel = WorldPanel(get_frames)
        self._world = GuardedMenu(self._panel, menu_model)
        return self

    def show_menus(self) -> None:
        """Render the menu bar; the ImGui runner's per-frame callback."""
        from imgui_bundle import imgui

        self._bar.draw(imgui)

    def render_bar(self, imgui: Any) -> None:
        """Render the menu model as the application menu bar."""
        self._bar.draw(imgui)

    def render_world_panel(self, imgui: Any) -> None:
        """Render the menu model in the World panel, while open."""
        self._world.draw(imgui)

    def check_world_menu_background_click(self, imgui: Any) -> None:
        """Toggle the World panel on a background left click."""
        self._panel.check_background_click(imgui)

    @property
    def world_menu_open(self) -> bool:
        """Return whether the World panel is showing."""
        return self._panel.is_open
