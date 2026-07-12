"""WriteSeam — the one place the ABC and legacy write models diverge.

Field mutation is the single obligation the two element models do not meet
uniformly: an ABC element is patched in place, a legacy frozen value is realized
by ``dataclasses.replace``. This collaborator confines that divergence to one
``isinstance`` gate, hands the write path a model-agnostic
:class:`~punt_lux.domain.hub.field_realization.FieldRealization`, and enforces
the mixed-migration rule that a legacy element below a legacy composite defers to
``show``. It is deletable at migration's end: with no legacy elements, the legacy
branch has zero live inputs and the ABC branch is the whole design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.field_realization import (
    AbcFieldRealization,
    FieldRealization,
    LegacyFieldRealization,
)
from punt_lux.domain.hub.write_errors import (
    ImmutableFieldError,
    NestedLegacyWriteError,
)
from punt_lux.domain.ids import ElementId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.ids import SceneId

__all__ = ["WriteSeam"]

# ``id`` is the store's index key and ``kind`` selects the renderer and contract;
# no field patch may change either, for either element model.
_IMMUTABLE_FIELDS = frozenset({"id", "kind"})


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

        The immutable-field constraint (``id``/``kind``) is checked first, before
        the model dispatch, so both models refuse it for the same reason. An ABC
        element (root or nested) patches in place; a legacy root is realized by
        ``replace`` and rebound; a legacy element nested below a legacy composite
        is rejected fail-loud, directing the client to ``show``.
        """
        self._reject_immutable_field(element_id, fields)
        element = self._index.lookup(scene_id, element_id)
        if isinstance(element, AbcElement):
            return AbcFieldRealization(element, fields)
        self._require_legacy_root(scene_id, element_id)
        return LegacyFieldRealization(
            self._index, scene_id, element_id, element, fields
        )

    @staticmethod
    def _reject_immutable_field(
        element_id: ElementId, fields: Mapping[str, object]
    ) -> None:
        """Raise ``ImmutableFieldError`` if the patch names ``id`` or ``kind``."""
        for key in fields:
            if key in _IMMUTABLE_FIELDS:
                raise ImmutableFieldError(element_id=element_id, field=key)

    def guard_removal(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Raise if removing ``element_id`` defers to ``show``.

        An ABC element and a legacy root remove cleanly; a legacy element nested
        below a legacy composite would leave its frozen parent holding it by
        reference, so its removal defers to a whole-tree ``show`` on the same
        grounds as a nested-legacy field patch.
        """
        element = self._index.lookup(scene_id, element_id)
        if isinstance(element, AbcElement):
            return
        self._require_legacy_root(scene_id, element_id)

    def set_property(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        field: str,
        value: object,
    ) -> None:
        """Apply a single-field patch to an indexed ABC element in place.

        The store-level ``SetProperty`` primitive (the D21 dispatch and direct
        store callers). Legacy wire dataclasses are frozen; a ``SetProperty``
        against one is a programmer error at this primitive and raises
        ``TypeError`` — the authoritative batch write reaches legacy roots
        through :meth:`field_realization` instead.
        """
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
        """Return the kind of the scene-root whose subtree holds ``element_id``."""
        for root in self._index.scene_roots(scene_id):
            root_id = ElementId(root.id)
            if element_id in self._children.descendants(scene_id, root_id):
                return root.kind
        return "container"
