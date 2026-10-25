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
    from collections.abc import Mapping, Sequence

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
                return (
                    f"an element tree nests deeper than {MAX_ELEMENT_NESTING} "
                    "levels of JSON (a container counts two a level); flatten it"
                )
        return None

    @staticmethod
    def _depth(root: HasWireForm) -> int:
        """Return how many brackets deep ``root``'s wire form nests."""
        try:
            wire: object = root.to_dict()
        except RecursionError:
            return MAX_ELEMENT_NESTING + 1
        deepest = 0
        pending: list[tuple[object, int]] = [(wire, 1)]
        while pending:
            value, depth = pending.pop()
            if isinstance(value, dict):
                deepest = max(deepest, depth)
                pending.extend(
                    (v, depth + 1) for v in cast("dict[str, object]", value).values()
                )
            elif isinstance(value, list | tuple):
                deepest = max(deepest, depth)
                pending.extend((v, depth + 1) for v in cast("list[object]", value))
        return deepest
