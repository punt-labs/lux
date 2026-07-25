"""``Anonymizable`` — the capability to re-stamp an anonymous element's id.

A wire element may arrive anonymous (empty id). The dual-write pump keys the
domain ``Display`` by element id, so repeated anonymous elements in one scene
would collide on a shared ``""`` slot. A frozen dataclass is re-stamped with
``dataclasses.replace``; an Element-ABC leaf cannot go through ``replace``, so
it exposes this single-method capability (PY-DP-11) instead — the pump asks the
element for an id-stamped *copy*, leaving the wire/renderer original untouched.

Only kinds that legitimately arrive anonymous (``separator``) implement this;
every other ABC kind requires an explicit id and the pump refuses to synthesize
one for it.
"""

from __future__ import annotations

from typing import Protocol, Self, runtime_checkable

__all__ = ["Anonymizable"]


@runtime_checkable
class Anonymizable(Protocol):
    """An element that can return an id-stamped copy of itself."""

    def with_synthesized_id(self, new_id: str) -> Self:
        """Return a copy of this element carrying ``new_id`` as its identity."""
        ...
