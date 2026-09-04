"""The menu model — the one description of the menu the display renders.

A :class:`MenuModel` is the whole menu: the display's own menus, the bars an
agent submitted with ``set_menu``, and the ``Clients`` menu the Hub composes
— one submenu per live client — in that order. Every surface that shows
menus renders this one object, so no surface can hold a menu another cannot.

A menu is a menu at any depth: :class:`Submenu` holds entries, and an entry
may itself be a :class:`Submenu`, so the Hub's nesting arrives without a
second type. A replicated menu becomes a :class:`Submenu` through
:meth:`Submenu.from_wire`, which takes the checked :class:`WireMenu` rather
than the payload it came from -- fields were narrowed at the boundary
(:mod:`punt_lux.display.menus.wire`), so nothing here re-checks a type.
Turning that wire data into entries is :mod:`punt_lux.display.menus.wire_decode`'s
job (PY-IC-6): this module holds a label and renders entries, nothing more.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.wire_decode import WireMenuDecoder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.display.menus.entries import MenuEntry
    from punt_lux.display.menus.menu_click import MenuHandlers
    from punt_lux.display.menus.wire import WireMenu

__all__ = ["MenuModel", "Submenu"]


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
    def from_wire(cls, menu: WireMenu, handlers: MenuHandlers) -> Self:
        """Return the menu a checked replicated menu describes.

        An agent bar, the ``Clients`` menu, and a client's submenu inside it all
        arrive in the same shape, so all become menus here and a click on any
        leaf emits the same ``action="menu"`` invocation back to the Hub. A leaf
        carrying a ``frame_id`` also raises that frame Display-locally, before
        the invocation is even sent (DES-088: only the Display moves a frame).
        """
        decoder = WireMenuDecoder(handlers, cls.from_wire)
        return cls(menu.label, list(decoder.entries(menu)))

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
        fired = False
        for entry in self._entries:
            fired = entry.render(imgui) or fired
        return fired


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
        fired = False
        for section in self._sections:
            fired = section.render(imgui, id_suffix) or fired
        return fired
