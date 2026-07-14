"""ElementIdentity — an element's scene identity and the anonymous sentinel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

from punt_lux.domain.ids import ElementId

__all__ = ["ElementIdentity", "HasId"]


@runtime_checkable
class HasId(Protocol):
    """Anything carrying a scene id — the one field identity is read from."""

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        ...


@dataclass(frozen=True, slots=True)
class ElementIdentity:
    """An element's scene identity: a name, or the anonymous sentinel.

    Empty string is the anonymous sentinel — "no identity", not a reusable
    name. Anonymous elements (bare separators) carry it and may repeat freely
    across a scene; a named element's id must be unique. This class is the one
    place that decision lives, so every gate that must exempt anonymous
    elements reads the same predicate rather than re-testing ``not id``.
    """

    _name: str

    @classmethod
    def of(cls, element: HasId) -> Self:
        """Read ``element``'s identity from its ``id`` field."""
        return cls(element.id)

    @property
    def is_anonymous(self) -> bool:
        """Whether this is the anonymous sentinel — an empty id."""
        return not self._name

    @property
    def key(self) -> ElementId:
        """Return the id as an ``ElementId`` for store and registry keys."""
        return ElementId(self._name)
