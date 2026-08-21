"""MenuReplica — the display's menu state and the model both surfaces render.

The menu bar and the World panel are two projections of one :class:`MenuModel`.
This class holds the menu state the Hub replicates — the agent bars and the
Hub-composed ``Clients`` menu — composes the model from it alongside the
display's own menus, and hands that one model to each surface. An entry can
therefore never appear on one surface and not the other.

The display's own menus are built by :class:`OwnMenus`; what this class adds to
them is everything to do with the Hub: taking a replicated payload, holding what
was well-formed, and decoding it into menus whose clicks route back.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus import GuardedMenu, MenuBar, MenuModel, Submenu, WorldPanel
from punt_lux.display.menus.own_menus import OwnMenus
from punt_lux.display.menus.wire import WireMenu

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.window_chrome import WindowChromeCommands
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["MenuReplica"]


@final
class MenuReplica:
    """Own the replicated menu state and compose the menu every surface renders."""

    _emit_event: Callable[[RemoteEventHandlerInvocation], None]
    _own: OwnMenus
    _agent_menus: tuple[WireMenu, ...]
    _callback_menus: tuple[WireMenu, ...]
    _bar: GuardedMenu
    _panel: WorldPanel
    _world: GuardedMenu
    __slots__ = (
        "_agent_menus",
        "_bar",
        "_callback_menus",
        "_emit_event",
        "_own",
        "_panel",
        "_world",
    )

    def __new__(
        cls,
        *,
        emit_event: Callable[[RemoteEventHandlerInvocation], None],
        on_theme_selected: Callable[[str], None],
        on_decorated_toggled: Callable[[bool], None],
        on_opacity_changed: Callable[[float], None],
        on_font_scale_changed: Callable[[float], None],
        get_themes: Callable[[], list[Any]],
        get_decorated: Callable[[], bool],
        get_opacity: Callable[[], float],
        get_font_scale: Callable[[], float],
        get_frames: Callable[[], Mapping[str, Frame]],
        on_clear_all: Callable[[], None],
        on_fit_all: Callable[[], None],
        chrome: WindowChromeCommands,
    ) -> Self:
        self = super().__new__(cls)
        self._emit_event = emit_event
        self._own = OwnMenus(
            on_theme_selected=on_theme_selected,
            on_decorated_toggled=on_decorated_toggled,
            on_opacity_changed=on_opacity_changed,
            on_font_scale_changed=on_font_scale_changed,
            get_themes=get_themes,
            get_decorated=get_decorated,
            get_opacity=get_opacity,
            get_font_scale=get_font_scale,
            get_frames=get_frames,
            on_clear_all=on_clear_all,
            on_fit_all=on_fit_all,
            chrome=chrome,
        )
        self._agent_menus = ()
        self._callback_menus = ()
        self._bar = GuardedMenu(MenuBar(), self.menu_model)
        self._panel = WorldPanel(get_frames)
        self._world = GuardedMenu(self._panel, self.menu_model)
        return self

    # -- replicated menu state ----------------------------------------------

    @property
    def agent_menus(self) -> tuple[WireMenu, ...]:
        """Return the agent-defined menus the display holds."""
        return self._agent_menus

    def replace_agent_menus(self, payloads: Sequence[object]) -> None:
        """Take the replicated agent bar, keeping the menus that are well-formed.

        The socket is the boundary, so this is where a payload becomes a menu: a
        malformed one is rejected and logged here, by name, and never reaches the
        model the surfaces render or the inventory the display reports.
        """
        self._agent_menus = WireMenu.accepted(payloads, origin="agent_menus")

    @property
    def callback_menus(self) -> tuple[WireMenu, ...]:
        """Return the Hub-composed callback menus — the ``Clients`` menu."""
        return self._callback_menus

    def replace_callback_menus(self, payloads: Sequence[object]) -> None:
        """Take the replicated ``Clients`` menu, keeping what is well-formed."""
        self._callback_menus = WireMenu.accepted(payloads, origin="callback_menus")

    # -- the one model ------------------------------------------------------

    def menu_model(self) -> MenuModel:
        """Compose the menu: Lux, then Clients, then agent bars, then chrome.

        ``Clients`` (the callback menus) sits second-from-left so users can reach
        it without scanning past window-chrome menus. Rebuilt each frame, so every
        item reads live state — the theme in use, which frames are minimized,
        which sessions still hold a callback lease.
        """
        return MenuModel(
            [
                self._own.lux_section(),
                *(Submenu.from_wire(m, self._emit_event) for m in self._callback_menus),
                *(Submenu.from_wire(m, self._emit_event) for m in self._agent_menus),
                *self._own.chrome_sections(),
            ]
        )

    # -- the two surfaces ---------------------------------------------------

    def show_menus(self) -> None:
        """Render the menu bar. This is the ImGui runner's per-frame callback."""
        from imgui_bundle import imgui

        self.render_bar(imgui)

    def render_bar(self, imgui: Any) -> None:
        """Render the menu model as the application menu bar."""
        self._bar.draw(imgui)

    def render_world_panel(self, imgui: Any) -> None:
        """Render the menu model in the World panel, while the panel is open."""
        self._world.draw(imgui)

    def check_world_menu_background_click(self, imgui: Any) -> None:
        """Toggle the World panel on a left click on the window background."""
        self._panel.check_background_click(imgui)

    @property
    def world_menu_open(self) -> bool:
        """Return whether the World panel is showing."""
        return self._panel.is_open
