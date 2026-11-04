"""NestingCap -- how deeply one element's wire form may nest, the Hub's one limit.

A display answers ``inspect_scene`` with the scene's element tree as nested JSON,
and the wire guard refuses a frame whose brackets nest past ``MAX_NESTING``. A
frame the guard refuses retires the dial, so a scene the Hub accepts must never
yield a reply the guard refuses. The Hub therefore refuses any write that leaves an
element's wire form nested past ``MAX_ELEMENT_NESTING``, and the wire guard's bound
is derived from that same number (both live in :mod:`punt_lux.protocol.json_payload`).

The cap judges wire depth, never element kinds: whatever JSON an element's wire form
carries counts, whether it holds elements or arbitrary data. Only
:class:`~punt_lux.domain.hub.write_seam.WriteSeam` asks it, because every write to
the store goes through that seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from punt_lux.domain.element import Element as WireElement

__all__ = ["NestingCap"]


@final
class NestingCap:
    """Judges whether an element tree nests within ``MAX_ELEMENT_NESTING``."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def reason() -> str:
        """The agent-facing refusal, the same whichever door the write came through."""
        return (
            f"an element tree nests deeper than {MAX_ELEMENT_NESTING} "
            "levels of JSON (a container counts two a level); flatten it"
        )

    def depth(self, element: WireElement) -> int:
        """Return how many brackets deep ``element``'s wire form nests.

        A form too deep for the encoder to walk is deeper than any cap, so it
        reads as one bracket past it.
        """
        try:
            wire: object = element.to_dict()
        except RecursionError:
            return MAX_ELEMENT_NESTING + 1
        return self._deepest(wire)

    def refusal(self, roots: Sequence[WireElement]) -> str | None:
        """Return why ``roots`` nest too deeply to be installed, or ``None``."""
        if any(self.depth(root) > MAX_ELEMENT_NESTING for root in roots):
            return self.reason()
        return None

    def refusal_of_writes(
        self,
        roots: Sequence[WireElement],
        writes: Sequence[tuple[WireElement, WireElement]],
    ) -> str | None:
        """Return why ``roots`` would nest too deeply once every write is made.

        Each write is an element and what it would become. A batch in which no
        element's own wire form got deeper cannot deepen the scene, so it is not
        projected at all; otherwise every write is judged together, in place.
        """
        if not any(self.depth(after) > self.depth(before) for before, after in writes):
            return None
        return self.refusal_if_patched(
            roots, {before.id: after for before, after in writes}
        )

    def refusal_if_patched(
        self, roots: Sequence[WireElement], patched: Mapping[str, WireElement]
    ) -> str | None:
        """Return why ``roots`` would nest too deeply with ``patched`` in place.

        ``patched`` maps element ids to the elements that would replace them,
        every one at once: each takes its place under whatever surrounds it, a
        replaced container's own replacement included, so patches that nest inside
        one another are judged together. Nothing is changed.
        """
        try:
            wires = {
                element_id: element.to_dict() for element_id, element in patched.items()
            }
            projected = [self._substituted(root.to_dict(), wires) for root in roots]
        except RecursionError:
            return self.reason()
        deepest = max((self._deepest(wire) for wire in projected), default=0)
        return self.reason() if deepest > MAX_ELEMENT_NESTING else None

    @classmethod
    def _deepest(cls, wire: object) -> int:
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
