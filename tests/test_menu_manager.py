"""Characterization tests for MenuManager pure logic (no ImGui)."""

from __future__ import annotations

from typing import Any

from punt_lux.display.menu_manager import MenuManager
from punt_lux.protocol import RemoteEventHandlerInvocation


def _noop_emit(event: RemoteEventHandlerInvocation) -> None:
    pass


def _make_manager(**overrides: Any) -> MenuManager:
    """Build a MenuManager with stub callbacks for unit testing."""
    defaults: dict[str, Any] = {
        "emit_event": _noop_emit,
        "on_theme_selected": lambda _s: None,  # pyright: ignore[reportUnknownLambdaType]
        "on_decorated_toggled": lambda _b: None,  # pyright: ignore[reportUnknownLambdaType]
        "on_opacity_changed": lambda _f: None,  # pyright: ignore[reportUnknownLambdaType]
        "on_font_scale_changed": lambda _f: None,  # pyright: ignore[reportUnknownLambdaType]
        "get_themes": list,
        "get_decorated": lambda: True,
        "get_opacity": lambda: 1.0,
        "get_font_scale": lambda: 1.0,
        "get_frames": dict,
        "on_clear_all": lambda: None,
        "on_fit_all": lambda: None,
    }
    defaults.update(overrides)
    return MenuManager(**defaults)


class TestCallbackMenus:
    """The Hub-composed session-then-callback submenus the display renders."""

    def test_callback_menus_default_empty(self) -> None:
        assert _make_manager().callback_menus == []

    def test_callback_menus_setter_replaces_the_whole_set(self) -> None:
        mgr = _make_manager()
        submenus = [{"label": "voxd", "items": [{"label": "Music", "id": "v\x1fm"}]}]
        mgr.callback_menus = submenus
        assert mgr.callback_menus == submenus
        mgr.callback_menus = []
        assert mgr.callback_menus == []
