"""MenuReplica — the display's menu state and the model both surfaces render.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus import GuardedMenu, MenuBar, MenuModel, Submenu, WorldPanel
from punt_lux.display.menus.menu_click import MenuHandlers
from punt_lux.display.menus.own_menus import OwnMenus as OwnMenus  # reexport
from punt_lux.display.menus.wire import WireMenu
from punt_lux.display.replica.menu_stats import MenuStats
from punt_lux.domain.identity import HubId, HubScopedKey, HubScopedStore

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from punt_lux.display.replica.frame import Frame
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["MenuReplica"]

# One "Clients" submenu list per Hub -- the disambiguator two Hubs need.
_CALLBACK_MENUS_LOCAL = "callback_menus"


@final
class MenuReplica:
    """Own the replicated menu state and compose the menu every surface renders."""

    _emit_event: Callable[[RemoteEventHandlerInvocation], None]
    _on_raise_frame: Callable[[str], None]
    _own: OwnMenus
    _agent_menus: tuple[WireMenu, ...]
    _callback_menus: HubScopedStore[tuple[WireMenu, ...]]
    _bar: GuardedMenu
    _panel: WorldPanel
    _world: GuardedMenu
    __slots__ = (
        "_agent_menus",
        "_bar",
        "_callback_menus",
        "_emit_event",
        "_on_raise_frame",
        "_own",
        "_panel",
        "_world",
    )

    def __new__(
        cls,
        *,
        emit_event: Callable[[RemoteEventHandlerInvocation], None],
        on_raise_frame: Callable[[str], None],
        get_frames: Callable[[], Mapping[str, Frame]],
        own: OwnMenus,
    ) -> Self:
        """Compose a replica around an already-built :class:`OwnMenus`.

        The caller assembles ``own`` -- construction is one object's job, not
        a fourteen-parameter pass-through here.
        """
        self = super().__new__(cls)
        self._emit_event = emit_event
        self._on_raise_frame = on_raise_frame
        self._own = own
        self._agent_menus = ()
        self._callback_menus = HubScopedStore()
        self._bar = GuardedMenu(MenuBar(), self.menu_model)
        self._panel = WorldPanel(get_frames)
        self._world = GuardedMenu(self._panel, self.menu_model)
        return self

    # -- replicated menu state ----------------------------------------------

    @property
    def agent_menus(self) -> tuple[WireMenu, ...]:
        """The agent-defined menus the display holds."""
        return self._agent_menus

    def replace_agent_menus(self, payloads: Sequence[object]) -> None:
        """Take the replicated agent bar; drops malformed menus."""
        self._agent_menus = WireMenu.accepted(payloads, origin="agent_menus")

    @property
    def callback_menus(self) -> tuple[WireMenu, ...]:
        """Every live Hub's ``Clients`` menu, concatenated (not replaced)."""
        return tuple(chain.from_iterable(self._callback_menus.values()))

    def replace_callback_menus(
        self, payloads: Sequence[object], hub: HubId | None = None
    ) -> None:
        """Take one Hub's ``Clients`` submenus; ``hub`` defaults to a stub."""
        resolved_hub = hub if hub is not None else HubId.stub()
        menus = WireMenu.accepted(payloads, origin="callback_menus")
        key = HubScopedKey(resolved_hub, _CALLBACK_MENUS_LOCAL)
        self._callback_menus.put(key, menus)

    def forget_hub(self, hub: HubId) -> None:
        """Retire a departed Hub's callback menus, so a stale entry doesn't linger."""
        self._callback_menus.drop_hub(hub)

    @property
    def stats(self) -> MenuStats:
        """This replica's live menu counts, for diagnostics."""
        hub_count = len(self._callback_menus.hubs())
        return MenuStats.compute(self._agent_menus, self.callback_menus, hub_count)

    # -- the one model ------------------------------------------------------

    def menu_model(self) -> MenuModel:
        """Compose Lux, Clients, agent bars, chrome. Rebuilt each frame."""
        handlers = MenuHandlers(self._emit_event, self._on_raise_frame)
        return MenuModel(
            [
                self._own.lux_section(),
                *(Submenu.from_wire(m, handlers) for m in self.callback_menus),
                *(Submenu.from_wire(m, handlers) for m in self._agent_menus),
                *self._own.chrome_sections(),
            ]
        )

    # -- the two surfaces ---------------------------------------------------

    def show_menus(self) -> None:
        """Render the menu bar; the ImGui runner's per-frame callback."""
        from imgui_bundle import imgui

        self.render_bar(imgui)

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
