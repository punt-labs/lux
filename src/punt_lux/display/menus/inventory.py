"""MenuInventory — every menu line the display holds, and where it sits.

The Hub's ``list_menus`` reports the menu it composed. This reports the menu the
display actually received, so the two tiers can be compared rather than one
trusted for the other: a session that reached the Hub and not the display shows
up as a leaf the Hub has and the display does not.

A leaf carries the menus it sits under, outermost first — ``["Clients", "lux"]``
for a session's entry, ``["File"]`` for an agent bar's — because with the menu
nested, the label alone no longer says which menu a line belongs to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

__all__ = ["MenuInventory", "MenuLeaf", "MenuSource"]

# Who put a menu in the display: the agent's own bar, or a session's callbacks.
type MenuSource = Literal["agent", "session"]

# A menu as the Hub replicates it. The values are ``Any`` because this is the
# wire boundary — the payload is whatever JSON carried.
type WireMenu = Mapping[str, Any]

# The key that makes a wire item a submenu rather than a line.
_ITEMS = "items"


@final
class MenuLeaf:
    """One line the display holds, and the menus it sits under."""

    _source: MenuSource
    _path: tuple[str, ...]
    _label: str
    _id: str
    __slots__ = ("_id", "_label", "_path", "_source")

    def __new__(
        cls, source: MenuSource, path: tuple[str, ...], label: str, item_id: str
    ) -> Self:
        self = super().__new__(cls)
        self._source = source
        self._path = path
        self._label = label
        self._id = item_id
        return self

    @classmethod
    def of_item(cls, source: MenuSource, path: tuple[str, ...], item: WireMenu) -> Self:
        """Return the leaf a wire item describes, under the menus in *path*.

        A separator and an item the Hub sent no id for are both real lines the
        display holds, so both are reported — with an empty id, which is what
        the display has to click with.
        """
        return cls(source, path, str(item.get("label", "")), str(item.get("id", "")))

    @property
    def path(self) -> tuple[str, ...]:
        """The menus this line sits under, outermost first."""
        return self._path

    @property
    def label(self) -> str:
        """The text this line reads."""
        return self._label

    def to_report(self) -> dict[str, Any]:
        """Render as the untyped row an introspection query answers with."""
        return {
            "id": self._id,
            "label": self._label,
            "path": list(self._path),
            "source": self._source,
        }


@final
class MenuInventory:
    """Every leaf across every menu the display holds."""

    _leaves: tuple[MenuLeaf, ...]
    __slots__ = ("_leaves",)

    def __new__(cls, leaves: Sequence[MenuLeaf]) -> Self:
        self = super().__new__(cls)
        self._leaves = tuple(leaves)
        return self

    @classmethod
    def of(cls, sources: Sequence[tuple[MenuSource, Sequence[WireMenu]]]) -> Self:
        """Return the inventory of every source's bars, in the order given."""
        return cls(
            [
                leaf
                for source, bars in sources
                for bar in bars
                for leaf in cls._leaves_of(source, bar, ())
            ]
        )

    @property
    def leaves(self) -> tuple[MenuLeaf, ...]:
        """Every line held, in the order the menus present them."""
        return self._leaves

    def to_report(self) -> dict[str, Any]:
        """Render as the untyped payload an introspection query answers with."""
        rows = [leaf.to_report() for leaf in self._leaves]
        return {"menu_items": rows, "total": len(rows)}

    @classmethod
    def _leaves_of(
        cls, source: MenuSource, menu: WireMenu, path: tuple[str, ...]
    ) -> Iterator[MenuLeaf]:
        """Yield every leaf under *menu*, descending through its submenus."""
        here = (*path, str(menu.get("label", "")))
        for item in menu.get(_ITEMS, []):
            if _ITEMS in item:
                yield from cls._leaves_of(source, item, here)
            else:
                yield MenuLeaf.of_item(source, here, item)
