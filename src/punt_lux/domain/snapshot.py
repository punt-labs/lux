"""Read-only view over a Scene's current element state.

Returned by ``Display.snapshot(scene_id)``. Subscribers and tests use
this to inspect the authoritative tree without mutating it. The
``element`` accessor raises ``KeyError`` rather than returning ``None``
when the element does not exist (PY-EH-8): the caller's intent was to
read a known element; absence is an error, not a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from punt_lux.domain.element import Element
from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["SceneSnapshot"]


class SceneSnapshot:
    """Immutable snapshot of one Scene's elements at a point in time."""

    _scene_id: SceneId
    _elements: Mapping[ElementId, Element]

    def __new__(
        cls,
        scene_id: SceneId,
        elements: Mapping[ElementId, Element],
    ) -> Self:
        self = super().__new__(cls)
        self._scene_id = scene_id
        # Defensive copy — the snapshot must not observe later mutations.
        self._elements = dict(elements)
        return self

    @property
    def scene_id(self) -> SceneId:
        return self._scene_id

    @property
    def element_ids(self) -> frozenset[ElementId]:
        return frozenset(self._elements)

    def element(self, element_id: ElementId) -> Element:
        """Return the element with the given id or raise ``KeyError``."""
        elem = self._elements.get(element_id)
        if elem is None:
            msg = f"no such element in scene {self._scene_id!r}: {element_id!r}"
            raise KeyError(msg)
        return elem

    def has(self, element_id: ElementId) -> bool:
        """Return True iff this snapshot contains the element."""
        return element_id in self._elements
