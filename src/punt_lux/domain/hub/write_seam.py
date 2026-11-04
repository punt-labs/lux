"""WriteSeam — the one seam every element write to the store goes through.

A field patch on an ABC element is patched in place. This resolves the target at
the store index, hands the write path a ``FieldRealization``, and rejects a
target that is not a mutable ABC element. It is also where the nesting cap is
judged, for every kind of write: an install, an ``update`` batch, a store-level
property write and a handler's own patch each ask it, and it decides by comparing an
element's own wire depth before and after, so a write that deepens the wire form is
judged whatever field or payload deepened it.

An element write is judged in the scene that holds the element written, found by
the element itself, and refused when no scene holds it. That is one judge for every
route to a write: the agent's direct write, a handler fired by a display
interaction, and an observer woken by either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.batch_transaction import BatchTransaction
from punt_lux.domain.hub.field_gate import FieldGate
from punt_lux.domain.hub.field_realization import AbcFieldRealization
from punt_lux.domain.hub.write_refusals import NestingExceededError, UnheldTargetError
from punt_lux.domain.nesting_cap import NestingCap

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.field_realization import FieldRealization
    from punt_lux.domain.hub.write_result import WriteRejected
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
        element = self._index.lookup(scene_id, element_id)
        return AbcFieldRealization(self._mutable(element, scene_id, element_id), fields)

    def nesting_refusal(
        self, scene_id: SceneId, realizations: Sequence[FieldRealization]
    ) -> str | None:
        """Why the scene, with every realization applied at once, would nest too deeply.

        Judged on the whole batch before any of it is committed, so a refused batch
        changes nothing and no observer hears of it. The cap decides; the seam only
        hands it each target as it is and as it would become.
        """
        try:
            writes = [(r.current(), r.projected()[1]) for r in realizations]
            return NestingCap().refusal_of_writes(
                self._index.scene_roots(scene_id), writes
            )
        except RecursionError:  # a form too deep to build or measure is past the cap
            return NestingCap.reason()

    def admit(self, element: AbcElement, patch: Mapping[str, object]) -> None:
        """Raise unless ``patch`` may be written to ``element``; the one judge.

        The patch is measured in the scene that holds ``element``, whichever scene
        the writer acts for, so a handler or an observer reaching an element of
        another scene is judged there. An element no scene holds is refused: its
        scene, and so its cap, cannot be known.
        """
        realization = AbcFieldRealization(element, patch)
        scene_id = self._index.scene_of(realization.current())
        if scene_id is None:
            raise UnheldTargetError.of(element.id)
        refusal = self.nesting_refusal(scene_id, [realization])
        if refusal is not None:
            raise NestingExceededError.of(refusal)

    def commit(self, realizations: Sequence[FieldRealization]) -> WriteRejected | None:
        """Commit a batch as one transaction; why the judge refused it, if it did.

        The batch was judged whole before this; see :class:`BatchTransaction`.
        """
        return self.transaction().run(realizations)

    def transaction(self) -> BatchTransaction:
        """Return a transaction that commits under this seam's judge and cap."""
        return BatchTransaction(self.admit, self._require_final_state_within_cap)

    def _require_final_state_within_cap(self, written: Sequence[AbcElement]) -> None:
        """Raise :class:`NestingExceededError` if a scene written now nests too deep."""
        measured: set[SceneId] = set()
        for element in written:
            scene_id = self._index.scene_of(element)
            if scene_id is None:  # an element no scene holds: its cap cannot be known
                raise UnheldTargetError.of(element.id)
            if scene_id in measured:
                continue
            measured.add(scene_id)
            self.require_within_cap(self._index.scene_roots(scene_id))

    @staticmethod
    def require_within_cap(roots: Sequence[WireElement]) -> None:
        """Raise :class:`NestingExceededError` if ``roots`` would nest too deeply."""
        reason = NestingCap().refusal(roots)
        if reason is not None:
            raise NestingExceededError.of(reason)

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
        ``show`` performs. The patch runs under the judge, so a write that would nest
        the scene past the cap raises :class:`NestingExceededError` and changes
        nothing, and so does one an observer of the element makes in turn.
        """
        FieldGate.reject(element_id, {field: value})
        target = self._index.lookup(scene_id, element_id)
        realization = AbcFieldRealization(
            self._mutable(target, scene_id, element_id), {field: value}
        )
        refusal = self.nesting_refusal(scene_id, [realization])
        if refusal is not None:
            raise NestingExceededError.of(refusal)
        self.transaction().run_or_raise([realization])

    @staticmethod
    def _mutable(
        element: WireElement, scene_id: SceneId, element_id: ElementId
    ) -> AbcElement:
        """Return the looked-up target, requiring it be a mutable ABC element."""
        if not isinstance(element, AbcElement):
            msg = (
                f"write target {str(element_id)!r} in scene {str(scene_id)!r} "
                f"is not a mutable ABC Element"
            )
            raise TypeError(msg)
        return element
