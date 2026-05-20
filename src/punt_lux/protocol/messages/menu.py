"""Display-configuration messages — menu, theme, register-menu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

__all__ = [
    "MenuMessage",
    "RegisterMenuMessage",
    "ThemeMessage",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class MenuMessage:
    """Set custom menus in the menu bar (agent-extensible)."""

    menus: list[dict[str, Any]]  # [{label, items: [{label, id, shortcut?, enabled?}]}]
    type: Literal["menu"] = "menu"


@dataclass(frozen=True, slots=True)
class ThemeMessage:
    """Set the display theme."""

    theme: str  # snake_case theme name (e.g. "imgui_colors_light")
    type: Literal["theme"] = "theme"


@dataclass(frozen=True, slots=True)
class RegisterMenuMessage:
    """Register menu items owned by this client.

    Additive: each client's items are merged into the Tools menu.
    Replaces any previous registration from the same client (socket).
    Automatically cleaned up on disconnect.
    """

    items: list[dict[str, Any]]  # [{label, id, shortcut?, enabled?, icon?}]
    type: Literal["register_menu"] = "register_menu"


def _menu_to_dict(m: MenuMessage) -> dict[str, Any]:
    return {"type": m.type, "menus": m.menus}


def _theme_to_dict(m: ThemeMessage) -> dict[str, Any]:
    return {"type": m.type, "theme": m.theme}


def _register_menu_to_dict(m: RegisterMenuMessage) -> dict[str, Any]:
    return {"type": m.type, "items": m.items}


def _menu_from_dict(d: dict[str, Any]) -> MenuMessage:
    return MenuMessage(menus=d.get("menus", []))


def _theme_from_dict(d: dict[str, Any]) -> ThemeMessage:
    return ThemeMessage(theme=d["theme"])


def _register_menu_from_dict(d: dict[str, Any]) -> RegisterMenuMessage:
    raw = d.get("items")
    raw_items = cast("list[Any]", raw) if isinstance(raw, list) else []  # type: ignore[redundant-cast]
    return RegisterMenuMessage(items=[e for e in raw_items if isinstance(e, dict)])


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("menu", MenuMessage, _menu_to_dict, _menu_from_dict)
    register("theme", ThemeMessage, _theme_to_dict, _theme_from_dict)
    register(
        "register_menu",
        RegisterMenuMessage,
        _register_menu_to_dict,
        _register_menu_from_dict,
    )
