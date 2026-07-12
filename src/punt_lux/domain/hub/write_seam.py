"""WriteSeam — the one place the ABC and legacy write models diverge.

Field mutation is the single obligation the two models do not meet uniformly: an
ABC element is patched in place, a legacy frozen value realized by
``dataclasses.replace``. This confines that divergence to one ``isinstance`` gate,
hands the write path a model-agnostic ``FieldRealization``, and defers a legacy
element below a legacy composite to ``show``. Deletable at migration's end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.deferral_errors import NestedLegacyWriteError
from punt_lux.domain.hub.field_gate import FieldGate
from punt_lux.domain.hub.field_realization import (
    AbcFieldRealization,
    FieldRealization,
    LegacyFieldRealization,
)
from punt_lux.domain.ids import ElementId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.ids import SceneId

__all__ = ["WriteSeam"]


@final
class WriteSeam:
    """Resolve the realization of a field mutation over the authoritative store.

    Holds the store's index and child-edge collaborators so it can classify a
    target at the ``isinstance(element, AbcElement)`` seam: an ABC element (patch
    in place at any depth), a legacy root (``replace`` + rebind), or a legacy
    element nested below a legacy composite (defer to ``show``).
    """

    _index: ElementIndex
    _children: ChildIndex
    __slots__ = ("_children", "_index")

    def __new__(cls, index: ElementIndex, children: ChildIndex) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._children = children
        return self

    def field_realization(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        fields: Mapping[str, object],
    ) -> FieldRealization:
        """Return the realization of a field patch — the ABC/legacy seam.

        Forbidden fields are rejected first — an immutable or structural field
        never reaches the model dispatch. The field-name policy lives in
        ``FieldGate`` so both models reject ``id``/``kind`` and
        ``children``/``pages``/``tabs`` for one reason. An ABC element patches in
        place; a legacy root is realized by ``replace`` and rebound; a legacy
        element below a legacy composite defers to ``show``.
        """
        FieldGate.reject(element_id, fields)
        element = self._resolve_writable(scene_id, element_id)
        if isinstance(element, AbcElement):
            return AbcFieldRealization(element, fields)
        return LegacyFieldRealization(
            self._index, scene_id, element_id, element, fields
        )

    def is_present(self, scene_id: SceneId, element_id: ElementId) -> bool:
        """Return whether ``element_id`` is installed — lets removal stay idempotent."""
        return self._index.contains(scene_id, element_id)

    def guard_removal(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Raise if removing ``element_id`` defers to ``show``.

        An ABC element and a legacy root remove cleanly; a legacy element nested
        below a legacy composite would leave its frozen parent holding it by
        reference, so its removal defers to ``show`` like a nested-legacy patch.
        """
        self._resolve_writable(scene_id, element_id)

    def _resolve_writable(
        self, scene_id: SceneId, element_id: ElementId
    ) -> WireElement:
        """Return the target element, requiring a legacy target be a scene-root."""
        element = self._index.lookup(scene_id, element_id)
        if not isinstance(element, AbcElement):
            self._require_legacy_root(scene_id, element_id)
        return element

    def set_property(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        field: str,
        value: object,
    ) -> None:
        """Apply a single-field patch to an indexed ABC element in place.

        The store-level ``SetProperty`` primitive (D21 dispatch and direct store
        callers). The field gate runs first: a forbidden field (immutable or
        structural ``children``/``pages``/``tabs``) never reaches the store, since
        installing and evicting children — even on a migrated ABC composite — is
        work only ``show`` performs. Legacy wire dataclasses are frozen; a
        ``SetProperty`` against one is a programmer error and raises ``TypeError``.
        """
        FieldGate.reject(element_id, {field: value})
        element = self._index.lookup(scene_id, element_id)
        if not isinstance(element, AbcElement):
            msg = (
                f"SetProperty target {element_id!r} in scene {scene_id!r} "
                f"is not a mutable ABC Element"
            )
            raise TypeError(msg)
        element.apply_patch({field: value})

    def _require_legacy_root(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Raise ``NestedLegacyWriteError`` unless ``element_id`` is a root."""
        if self._children.is_root(scene_id, element_id):
            return
        raise NestedLegacyWriteError(
            scene_id=scene_id,
            element_id=element_id,
            root_kind=self._enclosing_root_kind(scene_id, element_id),
        )

    def _enclosing_root_kind(self, scene_id: SceneId, element_id: ElementId) -> str:
        """Return the kind of the scene-root whose subtree holds ``element_id``.

        A non-root element is a descendant of exactly one scene-root; if none holds
        it, the child-edge index and the element index disagree — a store-invariant
        violation that fails loud rather than returning a misleading placeholder.
        """
        for root in self._index.scene_roots(scene_id):
            root_id = ElementId(root.id)
            if element_id in self._children.descendants(scene_id, root_id):
                return root.kind
        msg = (
            f"non-root element {str(element_id)!r} in scene {str(scene_id)!r} "
            f"has no enclosing scene-root; child index and element index disagree"
        )
        raise ValueError(msg)
