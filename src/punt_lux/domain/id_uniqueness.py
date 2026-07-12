"""Whole-tree element-id uniqueness scan — the Hub's pre-install gate.

Id uniqueness is a tree-level invariant: no element id may repeat across a
submitted scene tree, whether the repeat is two roots sharing an id or a
root id reused by a buried child. A per-element ``validate()`` cannot see
the collision — it examines one element in isolation — so the check lives
in a stateful walk that remembers every id it has already seen.

The Display enforces the same invariant element-by-element at install time,
returning :class:`~punt_lux.domain.error.DuplicateIdError` from
``Display.apply``. The Hub enforces it here, before any install, so a
colliding tree is rejected whole and never partially installed. Both tiers
speak the same ``DuplicateIdError`` so a duplicate reads identically on
either side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_identity import ElementIdentity, HasId
from punt_lux.domain.error import DuplicateIdError
from punt_lux.domain.validation_walk import HasChildElements

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["DuplicateIdScanner"]


@final
class DuplicateIdScanner:
    """Finds the first repeated element id in a submitted scene tree.

    Stateless between calls. It recurses the same
    ``HasChildElements.child_elements()`` node set the validation walk and wire
    serializer use — so a buried child reusing a root id, or one hidden in a
    legacy tab or a paged group's off-screen panel, is caught.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def first_duplicate(
        self, scene_id: SceneId, roots: Sequence[object]
    ) -> DuplicateIdError | None:
        """Return the first ``DuplicateIdError`` in ``roots``, or ``None``.

        ``None`` is the "no collision" contract — the ids are unique and the
        tree may be installed. A non-``None`` result is the first clash in
        install order, ready to hand back to the client.
        """
        seen: set[ElementId] = set()
        for root in roots:
            found = self._scan(scene_id, root, seen)
            if found is not None:
                return found
        return None

    def _scan(
        self, scene_id: SceneId, element: object, seen: set[ElementId]
    ) -> DuplicateIdError | None:
        """Record ``element``'s id, then recurse; return the first clash.

        Anonymous elements (an empty id — e.g. bare separators) carry no
        identity to collide, so they are exempt.
        """
        if isinstance(element, HasId):
            identity = ElementIdentity.of(element)
            if not identity.is_anonymous:
                if identity.key in seen:
                    return DuplicateIdError(scene_id=scene_id, element_id=identity.key)
                seen.add(identity.key)
        if isinstance(element, HasChildElements):
            for child in element.child_elements():
                found = self._scan(scene_id, child, seen)
                if found is not None:
                    return found
        return None
