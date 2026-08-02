"""The menu model — the one description of the menu the display renders.

A :class:`MenuModel` is the whole menu: the display's own menus, the bars an
agent submitted with ``set_menu``, and the ``Clients`` menu the Hub
composes — one submenu per live client, holding that client's commands — in
that order. Every surface that shows menus renders
this one object, so no surface can hold a menu another surface does not.

A menu is a menu at any depth: :class:`Submenu` holds entries, and an entry may
itself be a :class:`Submenu`, so the Hub's nesting arrives without a second
type.

A replicated menu becomes a :class:`Submenu` through
:meth:`Submenu.from_wire`, which takes the checked :class:`WireMenu` rather than
the payload it came from: the fields were narrowed at the boundary
(:mod:`punt_lux.display.menus.wire`), so nothing here re-checks a type or
invents a value for a field that was not sent.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.entries import MenuItem, MenuSeparator
from punt_lux.display.menus.wire import WireMenu, WireSeparator
from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from punt_lux.display.menus.entries import MenuEntry
    from punt_lux.display.menus.wire import WireAction

__all__ = ["MenuModel", "Submenu"]

type EmitEvent = Callable[[RemoteEventHandlerInvocation], None]


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
        """Return the menu a checked replicated menu describes.

        An agent bar, the ``Clients`` menu, and a client's submenu inside it all
        arrive in the same shape, so all become menus here and a click on any
        leaf emits the same ``action="menu"`` invocation back to the Hub.
        """
        return cls(menu.label, list(cls._wire_entries(menu, emit)))

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
    def _wire_entries(cls, menu: WireMenu, emit: EmitEvent) -> Iterator[MenuEntry]:
        """Yield one entry per entry of the checked menu, in order.

        A nested menu is decoded as a menu, so a menu the Hub nested — the
        clients under ``Clients`` — renders as a nested menu here rather than as
        a line of its parent. The fork is on the type the boundary produced, not
        on a key of an untyped payload.
        """
        for entry in menu.entries:
            if isinstance(entry, WireMenu):
                yield cls.from_wire(entry, emit)
            elif isinstance(entry, WireSeparator):
                yield MenuSeparator()
            else:
                yield cls._wire_item(menu.label, entry, emit)

    @classmethod
    def _wire_item(
        cls, menu_label: str, action: WireAction, emit: EmitEvent
    ) -> MenuItem:
        """Return the clickable line one checked action describes."""
        return MenuItem(
            action.label,
            cls._invoke(menu_label, action.label, action.item_id, emit),
            shortcut=action.shortcut,
            enabled=action.enabled,
        )

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
