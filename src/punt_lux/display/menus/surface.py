"""The contract a menu surface answers, and the guard both surfaces are drawn through.

A surface is anything that takes a whole :class:`MenuModel` and shows it; the
menu bar and the World panel are the two Lux ships. :class:`GuardedMenu` pairs
one surface with the model it shows, so both surfaces are drawn through the same
object and neither can fail in a way the other does not.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.menus.model import MenuModel

logger = logging.getLogger(__name__)

__all__ = ["GuardedMenu", "MenuSurface"]


@runtime_checkable
class MenuSurface(Protocol):
    """Something that shows a whole menu model."""

    def render(self, imgui: Any, model: MenuModel) -> None:
        """Render every menu in *model* on this surface."""
        ...


@final
class GuardedMenu:
    """One surface, the model it shows, and the guard between them.

    Composing the model decodes the Hub-replicated payloads, and rendering it
    runs the action behind whatever the user clicked; either can raise. The
    render loop is the boundary, so a menu that cannot be drawn costs the frame
    that drew it and never the display.
    """

    _surface: MenuSurface
    _compose: Callable[[], MenuModel]
    __slots__ = ("_compose", "_surface")

    def __new__(cls, surface: MenuSurface, compose: Callable[[], MenuModel]) -> Self:
        self = super().__new__(cls)
        self._surface = surface
        self._compose = compose
        return self

    def draw(self, imgui: Any) -> None:
        """Compose the menu and show it, logging whatever could not be drawn."""
        try:
            self._surface.render(imgui, self._compose())
        except Exception:
            logger.exception("Error rendering menus")
