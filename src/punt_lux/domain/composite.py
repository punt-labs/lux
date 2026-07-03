"""Composite Protocol — structural contract for Elements that own children.

A Composite Element exposes a typed ``children`` tuple. Mirrors over
the scene graph (the domain pump, HubDisplay's installer) use
``isinstance(elem, Composite)`` to decide whether to recurse — this is
the OO replacement for ``hasattr(elem, "children")`` (banned by
PY-TS-10).

The Protocol is ``runtime_checkable`` so the recursion site can branch
on it directly. Concrete element kinds satisfy it implicitly by
declaring a ``children`` property whose type is a tuple of Elements.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from punt_lux.domain.element import Element

__all__ = ["Composite"]


@runtime_checkable
class Composite(Protocol):
    """An Element whose render walks an ordered tuple of child Elements.

    Structural contract: any Element with a ``children`` property
    returning ``tuple[Element, ...]`` satisfies this Protocol — wire
    dataclass composites and ABC composites alike.
    """

    @property
    def children(self) -> tuple[Element, ...]:
        """Return the composite's child elements in render order."""
        ...
