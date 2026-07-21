"""The Hub-owned menu types: the entries, the menu, and the push snapshot.

Menus are UI the agent submits, and submitted UI is Hub-authoritative state, so
these types live in the domain layer — the operations layer imports them, keeping
the one dependency arrow pointing operations → domain (PY-IC-9).

A menu entry is an action or a separator, never a half-formed action: the
discriminated :data:`MenuEntry` makes each shape explicit, and ``MenuAction``
requires a non-empty id so an id-less action cannot exist. An entry is
discriminated on the *presence of an id*, not its label: an entry with an id is an
action (even one labelled ``"---"``, which round-trips as an action), and the
id-less ``"---"`` sentinel is the only separator. Any other id-less entry is
malformed and rejected with a named-field error rather than silently coerced.

:class:`MenuState` is the whole menu state the replicator reads fresh at send time
and pushes — the agent bar and the World-menu tool items, as wire payloads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, cast, final

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Menu", "MenuAction", "MenuEntry", "MenuSeparator", "MenuState"]

# The wire label that stands in for a separator in the untyped menu payload.
_SEPARATOR_SENTINEL = "---"


class MenuAction(BaseModel):
    """A clickable menu item that fires an interaction when chosen."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["action"] = "action"
    id: str = Field(min_length=1)  # an id-less action is not a real state
    label: str = Field(min_length=1)  # a label-less action is not a real state
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


class Menu(BaseModel):
    """A labelled menu and the entries under it.

    A menu may itself appear as an entry of another menu — the display nests a
    per-client submenu under its Applications menu — so :data:`MenuEntry` includes
    ``Menu``.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["menu"] = "menu"
    label: str = Field(min_length=1)  # a label-less menu is not a real state
    items: list[MenuEntry]

    @classmethod
    def from_wire(cls, raw: object, *, index: int) -> Menu:
        """Build from one untyped menu, rejecting a malformed one by name.

        ``index`` names the menu's position for a field-located error; a menu
        that is not a mapping, that carries a missing/empty/non-string label, or
        that carries a present-but-non-list ``items`` or a malformed entry, is
        rejected rather than silently dropped or coerced to a blank menu. A
        missing ``items`` key is the one absence that defaults to no entries.
        """
        loc = f"menus.{index}"
        if not isinstance(raw, Mapping):
            msg = f"{loc}: expected a menu mapping, got {type(raw).__name__}"
            raise ValueError(msg)
        menu: Mapping[str, object] = cast("Mapping[str, object]", raw)
        label = menu.get("label")
        if not isinstance(label, str) or not label:
            msg = f"{loc}.label: expected a non-empty string"
            raise ValueError(msg)
        raw_items = menu.get("items", [])
        if isinstance(raw_items, str) or not isinstance(raw_items, Sequence):
            msg = f"{loc}.items: expected a list, got {type(raw_items).__name__}"
            raise ValueError(msg)
        items_seq: Sequence[object] = cast("Sequence[object]", raw_items)
        return cls(
            label=label,
            items=[
                cls._entry_from_wire(item, loc=f"{loc}.items.{i}")
                for i, item in enumerate(items_seq)
            ],
        )

    @classmethod
    def _entry_from_wire(cls, item: object, *, loc: str) -> MenuEntry:
        """Map one wire item to an action or the sentinel separator, or reject it.

        Every field is validated, never coerced: an entry with an id is an
        action whose id and label must both be non-empty strings and whose
        optional shortcut/icon, when present, must be strings. A malformed field
        is rejected by name (``{loc}.<field>``) rather than papered over with a
        ``str()`` or a blank default.
        """
        if not isinstance(item, Mapping):
            msg = f"{loc}: expected a menu item mapping, got {type(item).__name__}"
            raise ValueError(msg)
        entry: Mapping[str, object] = cast("Mapping[str, object]", item)
        raw_id = entry.get("id")
        if raw_id is not None:
            # An id makes this an action, whatever its label — even "---".
            return MenuAction(
                id=cls._require_str(raw_id, loc=f"{loc}.id"),
                label=cls._require_str(entry.get("label"), loc=f"{loc}.label"),
                shortcut=cls._optional_str(
                    entry.get("shortcut"), loc=f"{loc}.shortcut"
                ),
                icon=cls._optional_str(entry.get("icon"), loc=f"{loc}.icon"),
            )
        if entry.get("label") == _SEPARATOR_SENTINEL:
            return MenuSeparator()
        msg = f"{loc}: an id-less entry must be the {_SEPARATOR_SENTINEL!r} separator"
        raise ValueError(msg)

    @staticmethod
    def _require_str(value: object, *, loc: str) -> str:
        """Return ``value`` when it is a non-empty string, else reject it by name."""
        if not isinstance(value, str) or not value:
            msg = f"{loc}: expected a non-empty string"
            raise ValueError(msg)
        return value

    @staticmethod
    def _optional_str(value: object, *, loc: str) -> str | None:
        """Return a present string or ``None`` when absent; reject a non-string.

        ``None`` is the documented absence (no accelerator, no icon), not a
        give-up: a present-but-non-string value is rejected by name.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            msg = f"{loc}: expected a string"
            raise ValueError(msg)
        return value

    def to_wire(self) -> dict[str, object]:
        """Render as the untyped menu payload the display consumes."""
        return {"label": self.label, "items": [entry.to_wire() for entry in self.items]}


# A menu entry is an action, a separator, or a nested submenu, discriminated on
# ``kind``. Defined after ``Menu`` because it includes it; ``Menu.model_rebuild``
# resolves the forward reference in ``Menu.items``.
MenuEntry = Annotated[MenuAction | MenuSeparator | Menu, Field(discriminator="kind")]

Menu.model_rebuild()


@final
@dataclass(frozen=True, slots=True)
class MenuState:
    """The whole menu state to push: the agent bar and the World-menu tool items.

    Both are wire payloads — the display's own untyped menu dicts, composed from
    the registry's typed models at read time. The replicator resends the whole of
    each, so the newest registry state always wins.
    """

    bar: tuple[Mapping[str, object], ...]
    items: tuple[Mapping[str, object], ...]
