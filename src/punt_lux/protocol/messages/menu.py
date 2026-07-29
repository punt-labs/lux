"""Display-configuration messages — menu, callback-menu, theme."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from punt_lux.protocol.messages.callback_menu_message import CallbackMenuMessage

__all__ = [
    "CallbackMenuMessage",
    "MenuMessage",
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


def _menu_to_dict(m: MenuMessage) -> dict[str, Any]:
    return {"type": m.type, "menus": m.menus}


def _theme_to_dict(m: ThemeMessage) -> dict[str, Any]:
    return {"type": m.type, "theme": m.theme}


def _menu_from_dict(d: dict[str, Any]) -> MenuMessage:
    return MenuMessage(menus=d.get("menus", []))


def _theme_from_dict(d: dict[str, Any]) -> ThemeMessage:
    return ThemeMessage(theme=d["theme"])


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("menu", MenuMessage, _menu_to_dict, _menu_from_dict)
    register(
        "callback_menu",
        CallbackMenuMessage,
        CallbackMenuMessage.to_dict,
        CallbackMenuMessage.from_dict,
    )
    register("theme", ThemeMessage, _theme_to_dict, _theme_from_dict)
