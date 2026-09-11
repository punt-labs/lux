"""MenuReplica — composes the replicated menu state and the model both
surfaces render.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus import MenuModel, Submenu
from punt_lux.display.menus.menu_click import MenuHandlers
from punt_lux.display.menus.own_menus import OwnMenus as OwnMenus  # reexport
from punt_lux.display.replica.menu_surfaces import MenuSurfaces
from punt_lux.display.replica.replicated_menus import ReplicatedMenus
from punt_lux.domain.identity import HubId

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from punt_lux.display.menus.wire import WireMenu
    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.replica.menu_stats import MenuStats
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["MenuReplica"]

# replace_agent_menus/replace_callback_menus's own-Hub default; production
# dispatch always resolves and passes the sender's real HubId.
_NO_HUB = HubId.stub()


@final
class MenuReplica:
    """Compose the replicated menu state (:class:`ReplicatedMenus`) and the
    two rendering surfaces (:class:`MenuSurfaces`) that draw the one model
    built from it."""

    _emit_event: Callable[[RemoteEventHandlerInvocation], None]
    _on_raise_frame: Callable[[str], None]
    _own: OwnMenus
    _menus: ReplicatedMenus
    _surfaces: MenuSurfaces
    __slots__ = (
        "_emit_event",
        "_menus",
        "_on_raise_frame",
        "_own",
        "_surfaces",
    )

    def __new__(
        cls,
        *,
        emit_event: Callable[[RemoteEventHandlerInvocation], None],
        on_raise_frame: Callable[[str], None],
        get_frames: Callable[[], Mapping[str, Frame]],
        own: OwnMenus,
    ) -> Self:
        """Compose a replica around an already-built :class:`OwnMenus`."""
        self = super().__new__(cls)
        self._emit_event = emit_event
        self._on_raise_frame = on_raise_frame
        self._own = own
        self._menus = ReplicatedMenus()
        self._surfaces = MenuSurfaces(menu_model=self.menu_model, get_frames=get_frames)
        return self

    @property
    def agent_menus(self) -> tuple[WireMenu, ...]:
        return self._menus.agent_menus

    def replace_agent_menus(
        self, payloads: Sequence[object], hub: HubId = _NO_HUB
    ) -> None:
        """Take one Hub's agent bar; drops malformed menus. ``hub`` defaults
        to a stub for a caller with no live Hub connection in play."""
        self._menus.replace_agent_menus(payloads, hub)

    @property
    def callback_menus(self) -> tuple[WireMenu, ...]:
        return self._menus.callback_menus

    def replace_callback_menus(
        self, payloads: Sequence[object], hub: HubId = _NO_HUB
    ) -> None:
        """Take one Hub's ``Clients`` submenus; ``hub`` defaults to a stub."""
        self._menus.replace_callback_menus(payloads, hub)

    def forget_hub(self, hub: HubId) -> None:
        """Retire a departed Hub's agent and callback menus, so neither
        lingers as a stale entry."""
        self._menus.forget_hub(hub)

    @property
    def stats(self) -> MenuStats:
        """This replica's live menu counts, for diagnostics."""
        return self._menus.stats

    def menu_model(self) -> MenuModel:
        """Compose Lux, Clients, agent bars, chrome. Rebuilt each frame."""
        handlers = MenuHandlers(self._emit_event, self._on_raise_frame)
        return MenuModel(
            [
                self._own.lux_section(),
                *(Submenu.from_wire(m, handlers) for m in self._menus.callback_menus),
                *(Submenu.from_wire(m, handlers) for m in self._menus.agent_menus),
                *self._own.chrome_sections(),
            ]
        )

    def show_menus(self) -> None:
        """Render the menu bar; the ImGui runner's per-frame callback."""
        self._surfaces.show_menus()

    def render_bar(self, imgui: Any) -> None:
        """Render the menu model as the application menu bar."""
        self._surfaces.render_bar(imgui)

    def render_world_panel(self, imgui: Any) -> None:
        """Render the menu model in the World panel, while open."""
        self._surfaces.render_world_panel(imgui)

    def check_world_menu_background_click(self, imgui: Any) -> None:
        """Toggle the World panel on a background left click."""
        self._surfaces.check_world_menu_background_click(imgui)

    @property
    def world_menu_open(self) -> bool:
        """Return whether the World panel is showing."""
        return self._surfaces.world_menu_open
