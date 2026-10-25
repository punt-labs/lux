"""NestingCap -- how deeply one element's wire form may nest, the Hub's one limit.

A display answers ``inspect_scene`` with the scene's element tree as nested JSON,
and the wire guard refuses a frame whose brackets nest past ``MAX_NESTING``. A
frame the guard refuses retires the dial, so a scene the Hub accepts must never
yield a reply the guard refuses. The Hub therefore refuses, when it validates a
submitted tree (DES-039), any element whose wire form nests past
``MAX_ELEMENT_NESTING``, and the wire guard's bound is derived from that same
number (both live in :mod:`punt_lux.protocol.json_payload`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, cast, final, runtime_checkable

from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

__all__ = ["NestingCap"]


@runtime_checkable
class HasWireForm(Protocol):
    """An element that can say what it looks like on the wire."""

    def to_dict(self) -> Mapping[str, object]:
        """Return the element's JSON-compatible wire dict."""
        ...


@final
class NestingCap:
    """Judges whether a submitted tree nests within ``MAX_ELEMENT_NESTING``."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def refusal(self, roots: Sequence[object]) -> str | None:
        """Return why ``roots`` nest too deeply to be installed, or ``None``."""
        for root in roots:
            if (
                isinstance(root, HasWireForm)
                and self._depth(root) > MAX_ELEMENT_NESTING
            ):
                return self._reason()
        return None

    def refusal_if_patched(
        self, roots: Sequence[object], patched: Mapping[str, object]
    ) -> str | None:
        """Return why ``roots`` would nest too deeply with ``patched`` in place.

        ``patched`` maps element ids to the elements that would replace them,
        every one at once: each takes its place under whatever surrounds it, a
        replaced container's own replacement included, so patches that nest inside
        one another are judged together. Nothing is changed.
        """
        wires = {
            element_id: element.to_dict()
            for element_id, element in patched.items()
            if isinstance(element, HasWireForm)
        }
        try:
            projected = [
                self._substituted(root.to_dict(), wires)
                for root in roots
                if isinstance(root, HasWireForm)
            ]
        except RecursionError:
            return self._reason()
        deepest = max(
            (depth for wire in projected for _node, depth in self._nodes(wire)),
            default=0,
        )
        return self._reason() if deepest > MAX_ELEMENT_NESTING else None

    @staticmethod
    def _reason() -> str:
        return (
            f"an element tree nests deeper than {MAX_ELEMENT_NESTING} "
            "levels of JSON (a container counts two a level); flatten it"
        )

    @classmethod
    def _depth(cls, root: HasWireForm) -> int:
        """Return how many brackets deep ``root``'s wire form nests."""
        try:
            wire: object = root.to_dict()
        except RecursionError:
            return MAX_ELEMENT_NESTING + 1
        return max((depth for _node, depth in cls._nodes(wire)), default=0)

    @classmethod
    def _substituted(cls, value: object, wires: Mapping[str, object]) -> object:
        """``value`` with every element in ``wires`` replaced by its wire form.

        Top-down, so a replaced container's replacement is searched in turn for the
        elements nested inside it.
        """
        if isinstance(value, dict):
            members = cast("dict[str, object]", value)
            element_id = members.get("id")
            if (
                "kind" in members
                and isinstance(element_id, str)
                and element_id in wires
            ):
                members = cast("dict[str, object]", wires[element_id])
                wires = {k: v for k, v in wires.items() if k != element_id}
            return {k: cls._substituted(v, wires) for k, v in members.items()}
        if isinstance(value, list | tuple):
            return [cls._substituted(v, wires) for v in cast("list[object]", value)]
        return value

    @staticmethod
    def _nodes(wire: object) -> Iterator[tuple[object, int]]:
        """Every object and array in ``wire`` with the bracket depth it opens at."""
        pending: list[tuple[object, int]] = [(wire, 1)]
        while pending:
            value, depth = pending.pop()
            if isinstance(value, dict):
                yield value, depth
                pending.extend(
                    (v, depth + 1) for v in cast("dict[str, object]", value).values()
                )
            elif isinstance(value, list | tuple):
                yield value, depth
                pending.extend((v, depth + 1) for v in cast("list[object]", value))
