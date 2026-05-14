"""Characterization tests for MenuManager pure logic (no ImGui)."""

from __future__ import annotations

from typing import Any

from punt_lux.display.menu_manager import MenuManager
from punt_lux.protocol import InteractionMessage


def _noop_emit(event: InteractionMessage) -> None:
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
        "get_client_names": dict,
        "on_clear_all": lambda: None,
        "on_fit_all": lambda: None,
    }
    defaults.update(overrides)
    return MenuManager(**defaults)


class TestSanitizeMenuItems:
    """Tests for MenuManager.sanitize_menu_items."""

    def test_rejects_duplicate_owner(self) -> None:
        """Registering an item ID already owned by a different fd returns None."""
        mgr = _make_manager()
        # Simulate fd=10 owning item "action-1"
        mgr.handle_register_menu(10, [{"id": "action-1", "label": "Do Thing"}])

        # fd=20 tries to register the same item ID
        result = mgr.sanitize_menu_items(20, [{"id": "action-1", "label": "Conflict"}])
        assert result is None

    def test_deduplicates_within_registration(self) -> None:
        """Duplicate item IDs within one registration are collapsed."""
        mgr = _make_manager()
        items: list[dict[str, Any]] = [
            {"id": "btn-1", "label": "First"},
            {"id": "btn-1", "label": "Duplicate"},
            {"id": "btn-2", "label": "Second"},
        ]
        result = mgr.sanitize_menu_items(5, items)
        assert result is not None
        ids = [i["id"] for i in result if "id" in i]
        assert ids == ["btn-1", "btn-2"]

    def test_handle_register_menu_updates_owners(self) -> None:
        """Ownership tracking maps item IDs to the registering fd."""
        mgr = _make_manager()
        mgr.handle_register_menu(
            7,
            [
                {"id": "alpha", "label": "Alpha"},
                {"id": "beta", "label": "Beta"},
            ],
        )
        assert mgr.menu_owners == {"alpha": 7, "beta": 7}
        assert 7 in mgr.menu_registrations
        assert len(mgr.menu_registrations[7]) == 2

    def test_handle_register_menu_replaces_previous(self) -> None:
        """Re-registering from same fd replaces old items and ownership."""
        mgr = _make_manager()
        mgr.handle_register_menu(3, [{"id": "old", "label": "Old"}])
        assert mgr.menu_owners == {"old": 3}

        mgr.handle_register_menu(3, [{"id": "new", "label": "New"}])
        assert mgr.menu_owners == {"new": 3}
        assert "old" not in mgr.menu_owners

    def test_clear_menus_empties_state(self) -> None:
        """clear_menus removes all registrations and owners."""
        mgr = _make_manager()
        mgr.handle_register_menu(5, [{"id": "x", "label": "X"}])
        mgr.clear_menus()
        assert mgr.menu_registrations == {}
        assert mgr.menu_owners == {}

    def test_on_client_disconnected_cleans_up(self) -> None:
        """Disconnecting a client removes its registrations and ownership."""
        mgr = _make_manager()
        mgr.handle_register_menu(9, [{"id": "item-a", "label": "A"}])
        mgr.handle_register_menu(11, [{"id": "item-b", "label": "B"}])

        mgr.on_client_disconnected(9)
        assert 9 not in mgr.menu_registrations
        assert "item-a" not in mgr.menu_owners
        # fd=11 unaffected
        assert 11 in mgr.menu_registrations
        assert mgr.menu_owners["item-b"] == 11
