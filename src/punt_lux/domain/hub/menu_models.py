"""The Hub-owned menu composite, its separator leaf, and the entry family.

Menus are Hub-authoritative submitted UI, so these types live in the domain layer
(operations → domain, PY-IC-9). The clickable :class:`MenuAction` leaf lives in
:mod:`punt_lux.domain.hub.menu_action`; this module owns the :class:`Menu`
container, the trivial :class:`MenuSeparator`, the :class:`WireMenuEntry` family
Protocol, and the discriminated :data:`MenuEntry` union.

Every entry owns both halves of its wire round-trip (``to_wire`` + a ``from_wire``
classmethod) and stamps itself for dispatch — the family behaviours the structural
:class:`WireMenuEntry` Protocol declares (families-share-by-Protocol, not a base
class); the pydantic union on ``kind`` stays the runtime shape. An entry is
discriminated on the *presence of an id* (see :meth:`Menu._entry_from_wire`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import (
    TYPE_CHECKING,
    Annotated,
    ClassVar,
    Literal,
    Protocol,
    Self,
    cast,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.domain.hub.menu_action import MenuAction

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

__all__ = ["Menu", "MenuAction", "MenuEntry", "MenuSeparator", "WireMenuEntry"]

# The wire label that stands in for a separator in the untyped menu payload.
SEPARATOR_SENTINEL = "---"


@runtime_checkable
class WireMenuEntry(Protocol):
    """A menu entry that renders and stamps itself. The family contract, structural.

    ``TYPE`` is the class-level family tag this Protocol reads; ``kind`` is the
    pydantic discriminator driving the runtime union — the two serve different
    type systems and carry the same string on purpose. The Protocol is
    load-bearing: :meth:`Menu.stamped_for` recurses over its items as this
    contract, and ``isinstance(x, WireMenuEntry)`` is the family-membership test.
    """

    TYPE: ClassVar[str]

    def to_wire(self) -> dict[str, object]:
        """Render as the untyped payload the display consumes."""
        ...

    def stamped_for(self, owner: ConnectionId, /) -> WireMenuEntry:
        """Return the entry with each leaf id stamped ``owner<US>id`` for dispatch."""
        ...


class MenuSeparator(BaseModel):
    """A divider between menu items."""

    model_config = ConfigDict(frozen=True)

    TYPE: ClassVar[str] = "separator"

    kind: Literal["separator"] = "separator"

    @classmethod
    def from_wire(cls) -> Self:
        """Build the separator; it carries no wire fields to read."""
        return cls()

    def stamped_for(self, _owner: ConnectionId) -> MenuSeparator:
        """Return the separator unchanged: it owns no leaf id to stamp."""
        return self

    def to_wire(self) -> dict[str, object]:
        """Render as the ``"---"`` separator sentinel the display consumes."""
        return {"label": SEPARATOR_SENTINEL}


class Menu(BaseModel):
    """A labelled menu and the entries under it.

    A menu may itself appear as an entry of another menu — the display nests a
    per-client submenu under its Applications menu — so :data:`MenuEntry` includes
    ``Menu``. It delegates each entry's decode to that entry's own ``from_wire``.
    """

    model_config = ConfigDict(frozen=True)

    TYPE: ClassVar[str] = "menu"

    kind: Literal["menu"] = "menu"
    label: str = Field(min_length=1)  # a label-less menu is not a real state
    items: list[MenuEntry]

    @classmethod
    def from_wire(cls, raw: object, *, index: int) -> Menu:
        """Build from one untyped menu, rejecting a malformed one by name.

        ``index`` names the menu's position for a field-located error; a menu that
        is not a mapping, carries a missing/empty/non-string label, or a
        present-but-non-list ``items`` or a malformed entry, is rejected rather
        than silently coerced. A missing ``items`` key defaults to no entries.
        """
        loc = f"menus.{index}"
        menu = cls._require_mapping(raw, loc=loc)
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
        """Discriminate one wire item to an action or the separator, delegating.

        An entry with an id is an action (whatever its label — even ``"---"``),
        decoded by :meth:`MenuAction.from_wire`; the id-less ``"---"`` sentinel is
        the separator; any other id-less entry is malformed and rejected by name.
        """
        entry = cls._require_mapping(item, loc=loc)
        if entry.get("id") is not None:
            return MenuAction.from_wire(entry, loc=loc)
        if entry.get("label") == SEPARATOR_SENTINEL:
            return MenuSeparator.from_wire()
        msg = f"{loc}: an id-less entry must be the {SEPARATOR_SENTINEL!r} separator"
        raise ValueError(msg)

    def stamped_for(self, owner: ConnectionId) -> Menu:
        """Return a copy with every leaf id stamped ``owner<US>id`` for dispatch.

        Recurses through nested submenus, so an agent item at any depth round-trips
        to the session that registered the bar.
        """
        return self.model_copy(
            update={"items": [entry.stamped_for(owner) for entry in self.items]}
        )

    def to_wire(self) -> dict[str, object]:
        """Render as the untyped menu payload the display consumes."""
        return {"label": self.label, "items": [entry.to_wire() for entry in self.items]}

    @staticmethod
    def _require_mapping(item: object, *, loc: str) -> Mapping[str, object]:
        """Return ``item`` as a mapping, or reject a non-mapping by name."""
        if not isinstance(item, Mapping):
            msg = f"{loc}: expected a menu mapping, got {type(item).__name__}"
            raise ValueError(msg)
        return cast("Mapping[str, object]", item)


# A menu entry is an action, a separator, or a nested submenu, discriminated on
# ``kind``. Defined after ``Menu`` because it includes it; ``Menu.model_rebuild``
# resolves the forward reference in ``Menu.items``.
MenuEntry = Annotated[MenuAction | MenuSeparator | Menu, Field(discriminator="kind")]

Menu.model_rebuild()
