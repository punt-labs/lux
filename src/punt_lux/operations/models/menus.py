"""Menu entry types and the menu, with the wire codec on the classes.

Menus are UI the agent submits, and submitted UI is what the Hub owns. A menu
entry is an action or a separator, never a half-formed action: the discriminated
:data:`MenuEntry` makes each shape explicit. The ``"---"`` separator sentinel
lives only at the wire boundary — ``Menu.from_wire`` maps it to a
:class:`MenuSeparator`, and ``to_wire`` maps back — so the typed model never
carries a magic label.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Menu", "MenuAction", "MenuEntry", "MenuSeparator"]

# The wire label that stands in for a separator in the untyped menu payload.
_SEPARATOR_SENTINEL = "---"


class MenuAction(BaseModel):
    """A clickable menu item that fires an interaction when chosen."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["action"] = "action"
    id: str
    label: str
    shortcut: str | None = None  # None when the item has no accelerator
    icon: str | None = None  # None when the item has no icon

    def to_wire(self) -> dict[str, object]:
        """Render as the untyped menu-item payload the display consumes."""
        item: dict[str, object] = {"label": self.label, "id": self.id}
        if self.shortcut is not None:
            item["shortcut"] = self.shortcut
        if self.icon is not None:
            item["icon"] = self.icon
        return item


class MenuSeparator(BaseModel):
    """A divider between menu items."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["separator"] = "separator"

    def to_wire(self) -> dict[str, object]:
        """Render as the ``"---"`` separator sentinel the display consumes."""
        return {"label": _SEPARATOR_SENTINEL}


# A menu entry is an action or a separator, discriminated on ``kind``.
MenuEntry = Annotated[MenuAction | MenuSeparator, Field(discriminator="kind")]


class Menu(BaseModel):
    """A labelled menu and the entries under it."""

    model_config = ConfigDict(frozen=True)

    label: str
    items: list[MenuEntry]

    @classmethod
    def from_wire(cls, raw: Mapping[str, object]) -> Menu:
        """Build from the untyped menu payload, mapping the separator sentinel."""
        raw_items = raw.get("items", [])
        items_seq: list[object] = (
            cast("list[object]", raw_items) if isinstance(raw_items, list) else []
        )
        return cls(
            label=str(raw.get("label", "")),
            items=[cls._entry_from_wire(item) for item in items_seq],
        )

    @classmethod
    def _entry_from_wire(cls, item: object) -> MenuEntry:
        """Map one wire item to an action or a separator."""
        if not isinstance(item, Mapping):
            return MenuSeparator()
        entry: Mapping[str, object] = cast("Mapping[str, object]", item)
        if entry.get("label") == _SEPARATOR_SENTINEL:
            return MenuSeparator()
        shortcut = entry.get("shortcut")
        icon = entry.get("icon")
        return MenuAction(
            id=str(entry.get("id", "")),
            label=str(entry.get("label", "")),
            shortcut=None if shortcut is None else str(shortcut),
            icon=None if icon is None else str(icon),
        )

    def to_wire(self) -> dict[str, object]:
        """Render as the untyped menu payload the display consumes."""
        return {"label": self.label, "items": [entry.to_wire() for entry in self.items]}
