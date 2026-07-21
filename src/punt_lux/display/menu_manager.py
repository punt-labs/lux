# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Menu state management and rendering for the Lux display server."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Self

from punt_lux.client_label import ClientLabel
from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)


class MenuManager:
    """Own all menu state and render menu bar + World panel.

    Receives callbacks for user selections (theme, opacity, etc.) but does
    not own the state those callbacks mutate.
    """

    _emit_event: Callable[[RemoteEventHandlerInvocation], None]
    _on_theme_selected: Callable[[str], None]
    _on_decorated_toggled: Callable[[bool], None]
    _on_opacity_changed: Callable[[float], None]
    _on_font_scale_changed: Callable[[float], None]
    _get_themes: Callable[[], list[Any]]
    _get_decorated: Callable[[], bool]
    _get_opacity: Callable[[], float]
    _get_font_scale: Callable[[], float]
    _get_frames: Callable[[], dict[str, Any]]
    _get_client_names: Callable[[], dict[int, str]]
    _on_clear_all: Callable[[], None]
    _on_fit_all: Callable[[], None]

    _agent_menus: list[dict[str, Any]]
    _menu_registrations: dict[int, list[dict[str, Any]]]
    _menu_owners: dict[str, int]
    _world_menu_open: bool
    _world_menu_pinned: bool
    _world_menu_spawn_pos: tuple[float, float] | None

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
        get_frames: Callable[[], dict[str, Any]],
        get_client_names: Callable[[], dict[int, str]],
        on_clear_all: Callable[[], None],
        on_fit_all: Callable[[], None],
    ) -> Self:
        self = super().__new__(cls)
        self._emit_event = emit_event
        self._on_theme_selected = on_theme_selected
        self._on_decorated_toggled = on_decorated_toggled
        self._on_opacity_changed = on_opacity_changed
        self._on_font_scale_changed = on_font_scale_changed
        self._get_themes = get_themes
        self._get_decorated = get_decorated
        self._get_opacity = get_opacity
        self._get_font_scale = get_font_scale
        self._get_frames = get_frames
        self._get_client_names = get_client_names
        self._on_clear_all = on_clear_all
        self._on_fit_all = on_fit_all
        self._agent_menus = []
        self._menu_registrations = {}
        self._menu_owners = {}
        self._world_menu_open = False
        self._world_menu_pinned = False
        self._world_menu_spawn_pos = None
        return self

    # -- public properties ---------------------------------------------------

    @property
    def agent_menus(self) -> list[dict[str, Any]]:
        """Return the list of agent-defined menus."""
        return self._agent_menus

    @agent_menus.setter
    def agent_menus(self, value: list[dict[str, Any]]) -> None:
        self._agent_menus = value

    @property
    def menu_registrations(self) -> dict[int, list[dict[str, Any]]]:
        """Return per-client menu item registrations."""
        return self._menu_registrations

    @property
    def menu_owners(self) -> dict[str, int]:
        """Return item-id to owning fd mapping."""
        return self._menu_owners

    @property
    def world_menu_open(self) -> bool:
        """Return whether the World panel is open."""
        return self._world_menu_open

    # -- menu bar rendering --------------------------------------------------

    def show_menus(self) -> None:
        """Render the full menu bar (Lux, Applications, Windows, Help, agents)."""
        from imgui_bundle import imgui

        try:
            self._show_lux_menu(imgui)
            self._show_apps_menu(imgui)
            self._show_window_menu(imgui)
            self._show_help_menu(imgui)
            for menu in self._agent_menus:
                self._show_agent_menu(imgui, menu)
        except Exception:
            logger.exception("Error rendering menus")

    def _show_lux_menu(self, imgui: Any) -> None:
        if not imgui.begin_menu("Lux"):
            return
        try:
            self._show_lux_items(imgui)
        finally:
            imgui.end_menu()

    def _show_lux_items(self, imgui: Any) -> bool:
        """Render Lux menu items. Returns True if any item clicked."""
        from imgui_bundle import hello_imgui

        clicked = False

        # Settings submenu: theme, chrome, opacity.
        if imgui.begin_menu("Settings"):
            try:
                clicked = self._show_settings_items(imgui) or clicked
            finally:
                imgui.end_menu()

        imgui.separator()

        if imgui.menu_item("Increase Font", "", False)[0]:  # noqa: FBT003
            scale = self._get_font_scale()
            self._on_font_scale_changed(min(round(scale + 0.1, 1), 3.0))
            clicked = True
        if imgui.menu_item("Decrease Font", "", False)[0]:  # noqa: FBT003
            scale = self._get_font_scale()
            self._on_font_scale_changed(max(round(scale - 0.1, 1), 0.5))
            clicked = True

        imgui.separator()

        if imgui.menu_item("Quit", "Cmd+Q", False)[0]:  # noqa: FBT003
            hello_imgui.get_runner_params().app_shall_exit = True
            clicked = True
        return clicked

    def _show_settings_items(self, imgui: Any) -> bool:
        """Render Settings submenu contents. Returns True if any item clicked."""
        from imgui_bundle import hello_imgui

        clicked = False

        # Theme picker.
        if imgui.begin_menu("Theme"):
            try:
                for theme in self._get_themes():
                    name = theme.name.replace("_", " ").title()
                    if imgui.menu_item(name, "", False)[0]:  # noqa: FBT003
                        hello_imgui.apply_theme(theme)
                        self._on_theme_selected(str(theme.name))
                        clicked = True
            finally:
                imgui.end_menu()

        imgui.separator()

        # Window chrome toggles.
        params = hello_imgui.get_runner_params()
        wp = params.app_window_params
        top_toggled, wp.top_most = imgui.menu_item("Always on Top", "", wp.top_most)
        if top_toggled:
            clicked = True

        toggled, _ = imgui.menu_item("Borderless", "", not self._get_decorated())
        if toggled:
            self._on_decorated_toggled(not self._get_decorated())
            clicked = True

        imgui.separator()

        # Opacity presets.
        if imgui.begin_menu("Opacity"):
            try:
                for pct in (25, 50, 75, 100):
                    val = pct / 100.0
                    current = abs(self._get_opacity() - val) < 0.05
                    if imgui.menu_item(f"{pct}%", "", current)[0]:
                        self._on_opacity_changed(val)
                        clicked = True
            finally:
                imgui.end_menu()
        return clicked

    def _show_apps_menu(self, imgui: Any) -> None:
        """Render the Applications menu in the menu bar."""
        if not self._menu_registrations:
            return
        if not imgui.begin_menu("Applications"):
            return
        try:
            for name, fd, items in self._sorted_app_clients():
                if imgui.begin_menu(f"{name}##{fd}"):
                    try:
                        items_sorted = sorted(items, key=lambda i: i.get("label") or "")
                        for item in items_sorted:
                            self._render_registered_item(imgui, item, "Applications")
                    finally:
                        imgui.end_menu()
        finally:
            imgui.end_menu()

    def _show_window_menu(self, imgui: Any) -> None:
        from imgui_bundle import hello_imgui

        if not imgui.begin_menu("Windows"):
            return
        try:
            self._show_window_frame_items(imgui)
            imgui.separator()
            self._show_window_chrome_items(imgui, hello_imgui)
        finally:
            imgui.end_menu()

    def _show_window_frame_items(self, imgui: Any) -> bool:
        """Render frame management items. Returns True if any item clicked."""
        clicked = False
        frames = self._get_frames()
        has_frames = bool(frames)
        has_visible = has_frames and any(not f.minimized for f in frames.values())
        has_minimized = has_frames and any(f.minimized for f in frames.values())

        if imgui.menu_item("Collapse All", "", False, has_visible)[0]:  # noqa: FBT003
            for f in frames.values():
                f.minimized = True
            clicked = True
        if imgui.menu_item("Expand All", "", False, has_minimized)[0]:  # noqa: FBT003
            for f in frames.values():
                f.minimized = False
            clicked = True
        if imgui.menu_item("Fit All", "", False, has_frames)[0]:  # noqa: FBT003
            self._on_fit_all()
            clicked = True
        return clicked

    def _show_window_chrome_items(self, imgui: Any, hello_imgui: Any) -> bool:
        """Render window chrome items. Returns True if any item clicked."""
        clicked = False
        if imgui.menu_item("Clear All", "", False)[0]:  # noqa: FBT003
            self._on_clear_all()
            clicked = True
        if imgui.menu_item("Reset Size", "", False)[0]:  # noqa: FBT003
            hello_imgui.change_window_size((1200, 800))
            clicked = True
        return clicked

    def _show_help_menu(self, imgui: Any) -> None:
        if not imgui.begin_menu("Help"):
            return
        try:
            self._show_help_items(imgui)
        finally:
            imgui.end_menu()

    def _show_help_items(self, imgui: Any) -> bool:
        """Render help items. Returns True if any item clicked."""
        from punt_lux import __version__

        imgui.menu_item(
            f"Lux v{__version__}",
            "",
            False,  # noqa: FBT003
            False,  # noqa: FBT003
        )
        return False  # version label is not clickable

    def _show_agent_menu(self, imgui: Any, menu: dict[str, Any]) -> None:
        if imgui.begin_menu(menu.get("label", "Custom")):
            try:
                for item in menu.get("items", []):
                    label = item.get("label")
                    if not isinstance(label, str):
                        continue
                    if label == "---":
                        imgui.separator()
                        continue
                    enabled = item.get("enabled", True)
                    clicked, _ = imgui.menu_item(
                        label,
                        item.get("shortcut", ""),
                        False,  # noqa: FBT003
                        enabled,
                    )
                    if clicked and isinstance(item.get("id"), str):
                        self._emit_event(
                            RemoteEventHandlerInvocation(
                                element_id=item["id"],
                                action="menu",
                                ts=time.time(),
                                value={
                                    "menu": menu.get("label", "Custom"),
                                    "item": label,
                                },
                            )
                        )
            finally:
                imgui.end_menu()

    # -- World panel ---------------------------------------------------------

    def check_world_menu_background_click(self, imgui: Any) -> None:
        """Toggle World panel on left-click on the main window background.

        Uses ``is_window_hovered()`` (no flags) which checks whether the
        *current* window (the main/root window at this point in the render
        loop) is hovered.  When a frame or the World panel is on top,
        the main window is not considered hovered, so clicks on frames
        are ignored.

        The dock bar renders later in the frame (its ``invisible_button``
        items and ``##dock_bar`` window haven't been emitted yet), so the
        hover checks above can't exclude it.  An explicit dock bar rect
        check handles this case.
        """
        if not imgui.is_mouse_clicked(imgui.MouseButton_.left):
            return
        if imgui.is_any_item_hovered():
            return
        # Current window = main window.  False when a frame covers the spot.
        if not imgui.is_window_hovered():
            return
        # Dock bar renders later in the frame, so its items/window aren't
        # yet in ImGui's hover state.  Reject clicks in its region.
        frames = self._get_frames()
        if any(f.minimized for f in frames.values()):
            viewport = imgui.get_main_viewport()
            mouse = imgui.get_mouse_pos()
            bar_top = viewport.pos.y + viewport.size.y - _DOCK_BAR_HEIGHT
            if mouse.y >= bar_top:
                return
        self._world_menu_open = not self._world_menu_open
        if self._world_menu_open:
            pos = imgui.get_mouse_pos()
            self._world_menu_spawn_pos = (pos.x, pos.y)

    def render_world_panel(self, imgui: Any) -> None:
        """Render the detached World menu as a floating window."""
        if not self._world_menu_open:
            return

        flags = (
            imgui.WindowFlags_.no_collapse.value
            | imgui.WindowFlags_.always_auto_resize.value
        )
        imgui.set_next_window_size((220, 0), imgui.Cond_.first_use_ever.value)
        if self._world_menu_spawn_pos is not None:
            imgui.set_next_window_pos(
                self._world_menu_spawn_pos, imgui.Cond_.always.value
            )
            self._world_menu_spawn_pos = None

        still_open = True
        _, still_open = imgui.begin("World###world_panel", still_open, flags)
        if not still_open:
            self._world_menu_open = False
            self._world_menu_pinned = False
            imgui.end()
            return

        # Pin dot -- filled when pinned, hollow when unpinned.
        pin_dot = "●" if self._world_menu_pinned else "○"
        if imgui.small_button(f"{pin_dot}##pin"):
            self._world_menu_pinned = not self._world_menu_pinned
        imgui.separator()

        clicked_any = self._render_world_panel_sections(imgui)

        imgui.end()

        # Auto-close on click when unpinned.
        if clicked_any and not self._world_menu_pinned:
            self._world_menu_open = False

    def _render_world_panel_sections(self, imgui: Any) -> bool:
        """Render all World panel sections. Returns True if any item clicked."""
        from imgui_bundle import hello_imgui

        clicked_any = False

        if imgui.begin_menu("Lux##world"):
            try:
                clicked_any = self._show_lux_items(imgui) or clicked_any
            finally:
                imgui.end_menu()

        # Applications submenu: agent-registered menu items grouped by client.
        if self._menu_registrations:
            clicked_any = self._render_world_panel_apps(imgui) or clicked_any

        if imgui.begin_menu("Windows##world"):
            try:
                clicked_any = self._show_window_frame_items(imgui) or clicked_any
                imgui.separator()
                chrome_clicked = self._show_window_chrome_items(imgui, hello_imgui)
                clicked_any = chrome_clicked or clicked_any
            finally:
                imgui.end_menu()
        if imgui.begin_menu("Help##world"):
            try:
                clicked_any = self._show_help_items(imgui) or clicked_any
            finally:
                imgui.end_menu()
        return clicked_any

    def _render_world_panel_apps(self, imgui: Any) -> bool:
        """Render Applications submenu in the World panel."""
        if not imgui.begin_menu("Applications##world"):
            return False
        clicked = False
        try:
            for name, fd, items in self._sorted_app_clients():
                if imgui.begin_menu(f"{name}##{fd}"):
                    try:
                        items_sorted = sorted(items, key=lambda i: i.get("label") or "")
                        for item in items_sorted:
                            rendered = self._render_registered_item(
                                imgui, item, "Applications"
                            )
                            clicked = clicked or rendered
                    finally:
                        imgui.end_menu()
        finally:
            imgui.end_menu()
        return clicked

    # -- registered menu item rendering --------------------------------------

    def _render_registered_item(
        self,
        imgui: Any,
        item: dict[str, Any],
        menu_name: str,
    ) -> bool:
        """Render a single registered menu item. Returns True if clicked."""
        label = item.get("label")
        if not isinstance(label, str):
            return False
        if label == "---":
            imgui.separator()
            return False
        enabled = item.get("enabled", True)
        clicked, _ = imgui.menu_item(
            label,
            item.get("shortcut", ""),
            False,  # noqa: FBT003
            enabled,
        )
        if clicked and isinstance(item.get("id"), str):
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=item["id"],
                    action="menu",
                    ts=time.time(),
                    value={
                        "menu": menu_name,
                        "item": label,
                    },
                )
            )
        return bool(clicked)

    # -- pure logic (no ImGui) -----------------------------------------------

    def sorted_app_clients(
        self,
    ) -> list[tuple[str, int, list[dict[str, Any]]]]:
        """Return registered clients sorted by display name (public API)."""
        return self._sorted_app_clients()

    def _sorted_app_clients(
        self,
    ) -> list[tuple[str, int, list[dict[str, Any]]]]:
        """Return registered clients sorted by display name."""
        clients: list[tuple[str, int, list[dict[str, Any]]]] = []
        for fd, items in self._menu_registrations.items():
            if items:
                raw = self._get_client_names().get(fd, f"Client {fd}")
                clients.append((self._display_name(raw), fd, items))
        clients.sort(key=lambda c: c[0].lower())
        return clients

    @staticmethod
    def _display_name(raw: str) -> str:
        """Derive a client's display name via the shared ``ClientLabel`` rule."""
        return ClientLabel.of(raw)

    def sanitize_menu_items(
        self, fd: int, items: list[Any]
    ) -> list[dict[str, Any]] | None:
        """Validate and deduplicate menu items for registration.

        Returns sanitized items, or None if registration should be rejected
        (item ID owned by a different client).
        """
        seen_ids: set[str] = set()
        sanitized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id is not None and not isinstance(item_id, str):
                continue
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                owner_fd = self._menu_owners.get(item_id)
                if owner_fd is not None and owner_fd != fd:
                    logger.warning(
                        "Menu item %r already owned by fd %d, "
                        "rejecting registration from fd %d",
                        item_id,
                        owner_fd,
                        fd,
                    )
                    return None
                seen_ids.add(item_id)
            sanitized.append(item)
        return sanitized

    def handle_register_menu(self, fd: int, items: list[Any]) -> None:
        """Register menu items owned by a client into the Applications menu."""
        sanitized = self.sanitize_menu_items(fd, items)
        if sanitized is None:
            return  # rejected -- ID collision
        # Remove old ownership entries for this fd
        self._menu_owners = {k: v for k, v in self._menu_owners.items() if v != fd}
        # Store new items (empty list clears this client's items)
        if sanitized:
            self._menu_registrations[fd] = sanitized
        else:
            self._menu_registrations.pop(fd, None)
        # Update ownership
        for item in sanitized:
            item_id = item.get("id")
            if item_id is not None:
                self._menu_owners[item_id] = fd

    def clear_menus(self) -> None:
        """Remove all menu registrations and ownership records."""
        self._menu_registrations.clear()
        self._menu_owners.clear()

    def on_client_disconnected(self, fd: int) -> None:
        """Clean up menu registrations when a client disconnects."""
        self._menu_registrations.pop(fd, None)
        self._menu_owners = {k: v for k, v in self._menu_owners.items() if v != fd}


# Module-level constant used by check_world_menu_background_click.
# Matches DisplayServer._DOCK_BAR_HEIGHT.
_DOCK_BAR_HEIGHT = 28.0
