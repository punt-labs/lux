"""Element Protocol — the structural contract every wire element class satisfies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, Self, runtime_checkable

__all__ = ["Element"]


@runtime_checkable
class Element(Protocol):
    """Structural contract for every visual thing in a Scene.

    Protocol — not ABC — so wire types satisfy this implicitly.  Properties
    cover both dataclass fields and explicit ``@property`` implementations.
    """

    @property
    def id(self) -> str:
        """Return the stable identity within the enclosing Scene."""
        ...

    @property
    def kind(self) -> str:
        """Return the wire discriminator, such as text or image."""
        ...

    @property
    def tooltip(self) -> str | None:
        """Return the tooltip, or None when the element has none."""
        ...

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        ...

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct from a JSON-decoded mapping."""
        ...
