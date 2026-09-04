"""Decode a checked wire menu's entries into the entries a menu renders.

Split from :mod:`punt_lux.display.menus.model` (PY-IC-6: one responsibility per
class) — :class:`~punt_lux.display.menus.model.Submenu` holds a label and
renders entries; turning wire data into click-ready :class:`MenuEntry` objects
is a separate concern with its own recursion. That recursion nests back into a
menu whenever a wire entry is itself a menu, so it needs to build a
``Submenu`` — but importing ``Submenu`` here would make this module and
``model.py`` import each other. ``build_submenu`` breaks the cycle: the caller
passes ``Submenu.from_wire`` in rather than this module reaching for it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.menus.entries import MenuItem, MenuSeparator
from punt_lux.display.menus.menu_click import ClickTarget
from punt_lux.display.menus.wire import WireMenu, WireSeparator
from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.display.menus.entries import MenuEntry
    from punt_lux.display.menus.menu_click import MenuHandlers
    from punt_lux.display.menus.wire import WireAction

__all__ = ["WireMenuDecoder"]


@final
class WireMenuDecoder:
    """Turns a checked wire menu's entries into click-ready entries.

    Holds what every entry in one decode needs: the click callbacks
    (:class:`MenuHandlers`) and the way to build a nested menu.
    """

    _handlers: MenuHandlers
    _build_submenu: Callable[[WireMenu, MenuHandlers], MenuEntry]
    __slots__ = ("_build_submenu", "_handlers")

    def __new__(
        cls,
        handlers: MenuHandlers,
        build_submenu: Callable[[WireMenu, MenuHandlers], MenuEntry],
    ) -> Self:
        self = super().__new__(cls)
        self._handlers = handlers
        self._build_submenu = build_submenu
        return self

    def entries(self, menu: WireMenu) -> Iterator[MenuEntry]:
        """Yield one entry per entry of the checked menu, in order.

        A nested menu is decoded via ``build_submenu``, so a menu the Hub
        nested — the clients under ``Clients`` — renders as a nested menu
        here rather than a line of its parent, forking on the boundary's
        type, not a key.
        """
        for entry in menu.entries:
            if isinstance(entry, WireMenu):
                yield self._build_submenu(entry, self._handlers)
            elif isinstance(entry, WireSeparator):
                yield MenuSeparator()
            else:
                yield self._wire_item(menu.label, entry)

    def _wire_item(self, menu_label: str, action: WireAction) -> MenuItem:
        """Return the clickable line one checked action describes."""
        target = ClickTarget(menu_label, action.label, action.item_id, action.frame_id)
        return MenuItem(
            action.label,
            self._invoke(target),
            shortcut=action.shortcut,
            enabled=action.enabled,
        )

    def _invoke(self, target: ClickTarget) -> Callable[[], None]:
        """Return the action that raises this item's frame, then reports the click.

        The raise runs first and Display-locally, before the Hub is even told
        the click happened — DES-088: only the Display moves a frame.
        """
        handlers = self._handlers

        def activate() -> None:
            if target.frame_id is not None:
                handlers.raise_frame(target.frame_id)
            handlers.emit(
                RemoteEventHandlerInvocation(
                    element_id=target.item_id,
                    action="menu",
                    ts=time.time(),
                    value={"menu": target.menu_label, "item": target.item_label},
                )
            )

        return activate
