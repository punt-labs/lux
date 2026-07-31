"""The menu model — the one description of the menu the display renders.

A :class:`MenuModel` is the whole menu: the display's own menus, the bars an
agent submitted with ``set_menu``, and the session-then-callback submenus the
Hub composes, in that order. Every surface that shows menus renders this one
object, so no surface can hold a menu another surface does not.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.entries import MenuItem, MenuSeparator
from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from punt_lux.display.menus.entries import MenuEntry

__all__ = ["MenuModel", "Submenu"]

# A menu as the Hub replicates it: {"label": str, "items": [{"label", "id", ...}]}.
# The values are ``Any`` because this is the wire boundary — the payload is
# whatever JSON carried, and each field is narrowed before it is used.
type WireMenu = Mapping[str, Any]
type EmitEvent = Callable[[RemoteEventHandlerInvocation], None]

_SEPARATOR_LABEL = "---"
_DEFAULT_MENU_LABEL = "Custom"


@final
class Submenu:
    """A labeled menu over an ordered list of entries."""

    _label: str
    _entries: tuple[MenuEntry, ...]
    __slots__ = ("_entries", "_label")

    def __new__(cls, label: str, entries: Sequence[MenuEntry]) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._entries = tuple(entries)
        return self

    @classmethod
    def from_wire(cls, menu: WireMenu, emit: EmitEvent) -> Self:
        """Return the menu a replicated wire payload describes.

        An agent bar and a session-then-callback submenu arrive in the same
        shape, so both become menus here and a click on either emits the same
        ``action="menu"`` invocation back to the Hub that owns the item.
        """
        label = menu.get("label", _DEFAULT_MENU_LABEL)
        title = label if isinstance(label, str) else _DEFAULT_MENU_LABEL
        return cls(title, list(cls._wire_entries(title, menu, emit)))

    @property
    def label(self) -> str:
        """Return the title this menu shows."""
        return self._label

    @property
    def entries(self) -> tuple[MenuEntry, ...]:
        """Return the entries under this menu, in display order."""
        return self._entries

    def render(self, imgui: Any, id_suffix: str = "") -> bool:
        """Render the menu, returning whether any of its entries was activated.

        *id_suffix* separates the ImGui ids of two surfaces rendering this same
        menu in one frame; it is not shown to the user.
        """
        if not imgui.begin_menu(f"{self._label}{id_suffix}"):
            return False
        try:
            return self._render_entries(imgui)
        finally:
            imgui.end_menu()

    def _render_entries(self, imgui: Any) -> bool:
        """Render every entry — all of them, whatever an earlier one returned."""
        activated = False
        for entry in self._entries:
            activated = entry.render(imgui) or activated
        return activated

    @classmethod
    def _wire_entries(
        cls, menu_label: str, menu: WireMenu, emit: EmitEvent
    ) -> Iterator[MenuEntry]:
        """Yield one entry per usable wire item, skipping the unlabeled ones."""
        for item in menu.get("items", []):
            label = item.get("label")
            if not isinstance(label, str):
                continue
            if label == _SEPARATOR_LABEL:
                yield MenuSeparator()
                continue
            shortcut = str(item.get("shortcut", ""))
            enabled = bool(item.get("enabled", True))
            item_id = item.get("id")
            if isinstance(item_id, str):
                yield MenuItem(
                    label,
                    cls._invoke(menu_label, label, item_id, emit),
                    shortcut=shortcut,
                    enabled=enabled,
                )
            else:
                yield MenuItem.inert(label, shortcut=shortcut, enabled=enabled)

    @staticmethod
    def _invoke(
        menu_label: str, item_label: str, item_id: str, emit: EmitEvent
    ) -> Callable[[], None]:
        """Return the action that sends this item's click back to the Hub."""

        def activate() -> None:
            emit(
                RemoteEventHandlerInvocation(
                    element_id=item_id,
                    action="menu",
                    ts=time.time(),
                    value={"menu": menu_label, "item": item_label},
                )
            )

        return activate


@final
class MenuModel:
    """Every menu the display shows, in the order they appear."""

    _sections: tuple[Submenu, ...]
    __slots__ = ("_sections",)

    def __new__(cls, sections: Sequence[Submenu]) -> Self:
        self = super().__new__(cls)
        self._sections = tuple(sections)
        return self

    @property
    def sections(self) -> tuple[Submenu, ...]:
        """Return the top-level menus, in display order."""
        return self._sections

    def render(self, imgui: Any, id_suffix: str = "") -> bool:
        """Render every menu, returning whether any item was activated."""
        activated = False
        for section in self._sections:
            activated = section.render(imgui, id_suffix) or activated
        return activated
