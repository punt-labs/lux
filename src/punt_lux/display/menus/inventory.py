"""MenuInventory — every menu line the display holds, and where it sits.

The Hub's ``list_menus`` reports the menu it composed. This reports the menu the
display actually received, so the two tiers can be compared rather than one
trusted for the other: a session that reached the Hub and not the display shows
up as a leaf the Hub has and the display does not.

A leaf carries the menus it sits under, outermost first — ``["Clients", "lux"]``
for a session's entry, ``["File"]`` for an agent bar's — because with the menu
nested, the label alone no longer says which menu a line belongs to.

The inventory reads checked menus (:mod:`punt_lux.display.menus.wire`), never
payloads: what the display holds was narrowed when it arrived, so this query
reports structure rather than re-deriving it, and a malformed payload can never
reach it to fail the whole report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Self, final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.display.menus.wire import WireLine, WireMenu

__all__ = ["MenuInventory", "MenuLeaf", "MenuSource"]

# Who put a menu in the display: the agent's own bar, or a session's callbacks.
type MenuSource = Literal["agent", "session"]


@final
class MenuLeaf:
    """One line the display holds, and the menus it sits under."""

    _source: MenuSource
    _path: tuple[str, ...]
    _line: WireLine
    __slots__ = ("_line", "_path", "_source")

    def __new__(cls, source: MenuSource, path: tuple[str, ...], line: WireLine) -> Self:
        self = super().__new__(cls)
        self._source = source
        self._path = path
        self._line = line
        return self

    @property
    def path(self) -> tuple[str, ...]:
        """The menus this line sits under, outermost first."""
        return self._path

    @property
    def label(self) -> str:
        """The text this line reads."""
        return self._line.label

    def to_report(self) -> dict[str, Any]:
        """Render as the untyped row an introspection query answers with.

        A separator is a real line the display holds, so it is reported like any
        other — with the empty id it has, which is what the display would have
        to click with.
        """
        return {
            "id": self._line.item_id,
            "label": self._line.label,
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
                MenuLeaf(source, path, line)
                for source, bars in sources
                for bar in bars
                for path, line in bar.lines()
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
