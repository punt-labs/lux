"""Element Protocol — the structural contract every wire element class satisfies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, Self, runtime_checkable

__all__ = ["Element"]


@runtime_checkable
class Element(Protocol):
    """The structural contract for every visual thing in a Scene.

    An Element has a stable identity (``id``), declares its wire kind
    (``kind``), and knows how to serialise to / deserialise from the JSON
    wire format via ``to_dict`` / ``from_dict``.

    Protocol — not ABC — so wire types satisfy this implicitly. The
    runtime_checkable decorator makes ``isinstance(x, Element)`` work
    against the structural shape; tests use this to assert that every
    concrete wire class conforms.
    """

    @property
    def id(self) -> str:
        """Return the stable identity within the enclosing Scene."""
        ...

    @property
    def kind(self) -> str:
        """Return the wire kind discriminator (e.g. ``"text"``, ``"image"``)."""
        ...

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        ...

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct from a JSON-decoded mapping."""
        ...
