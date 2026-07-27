"""WriteSeam — realize a field mutation over the authoritative store.

A field patch on an ABC element is patched in place. This resolves the target at
the store index, hands the write path a ``FieldRealization``, and rejects a
target that is not a mutable ABC element.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.field_gate import FieldGate
from punt_lux.domain.hub.field_realization import AbcFieldRealization

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.field_realization import FieldRealization
    from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["WriteSeam"]


@final
class WriteSeam:
    """Resolve the realization of a field mutation over the authoritative store.

    Holds the store's index so it can resolve a target and reject a write to a
    non-ABC element.
    """

    _index: ElementIndex
    __slots__ = ("_index",)

    def __new__(cls, index: ElementIndex) -> Self:
        self = super().__new__(cls)
        self._index = index
        return self

    def field_realization(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        fields: Mapping[str, object],
    ) -> FieldRealization:
        """Return the realization of a field patch on an indexed ABC element.

        Forbidden fields are rejected first via ``FieldGate`` (``id``/``kind``
        and structural ``children``/``tabs``); the target is then patched in place.
        """
        FieldGate.reject(element_id, fields)
        element = self._require_abc(scene_id, element_id)
        return AbcFieldRealization(element, fields)

    def is_present(self, scene_id: SceneId, element_id: ElementId) -> bool:
        """Return whether ``element_id`` is installed — lets removal stay idempotent."""
        return self._index.contains(scene_id, element_id)

    def set_property(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        field: str,
        value: object,
    ) -> None:
        """Apply a single-field patch to an indexed ABC element in place.

        The store-level ``SetProperty`` primitive. The field gate runs first: a
        forbidden field (immutable, or structural ``children``/``tabs``) never
        reaches the store, since installing and evicting children is work only
        ``show`` performs.
        """
        FieldGate.reject(element_id, {field: value})
        self._require_abc(scene_id, element_id).apply_patch({field: value})

    def _require_abc(self, scene_id: SceneId, element_id: ElementId) -> AbcElement:
        """Return the target, requiring it be a mutable ABC element."""
        element = self._index.lookup(scene_id, element_id)
        if not isinstance(element, AbcElement):
            msg = (
                f"write target {str(element_id)!r} in scene {str(scene_id)!r} "
                f"is not a mutable ABC Element"
            )
            raise TypeError(msg)
        return element
