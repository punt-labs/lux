"""Apply a batch of update patches to a scene's element tree."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.scene.widget_sync import WidgetSync

if TYPE_CHECKING:
    from punt_lux.protocol import Element, SceneMessage, UpdateMessage
    from punt_lux.scene.element_walk import ElementLocation, SceneTreeWalk
    from punt_lux.scene.widget_state import WidgetState

_log = logging.getLogger(__name__)


@final
class PatchApplier:
    """Apply an update's patch batch to a resolved scene's element tree.

    Owns the "apply a batch of patches" responsibility split out of
    :class:`SceneManager` — locate each patch target and remove it or set
    fields — while scene lifecycle (storing scenes, frames, ownership) stays on
    the manager. Tree navigation is delegated to a shared :class:`SceneTreeWalk`;
    mirroring a patched value into :class:`WidgetState` (and marking moved
    windows dirty) is delegated to a :class:`WidgetSync`.
    """

    __slots__ = ("_walk", "_widget_sync")

    _walk: SceneTreeWalk
    _widget_sync: WidgetSync

    def __new__(cls, *, walk: SceneTreeWalk, dirty_windows: set[str]) -> Self:
        self = super().__new__(cls)
        self._walk = walk
        self._widget_sync = WidgetSync(dirty_windows=dirty_windows)
        return self

    def apply(
        self, scene: SceneMessage, msg: UpdateMessage, ws: WidgetState | None
    ) -> None:
        """Apply every patch in ``msg`` to ``scene``'s element tree."""
        for patch in msg.patches:
            location = self._walk.find(scene.elements, patch.id)
            if location is None:
                self._warn_unreachable_patch(scene, patch.id, msg.scene_id)
                continue
            if patch.remove:
                self._remove_located(location, ws)
            elif patch.set:
                self._apply_patch_set(location, patch.set, ws, scene_id=msg.scene_id)

    def _remove_located(
        self, location: ElementLocation, ws: WidgetState | None
    ) -> None:
        """Detach the located element and clear its subtree's widget state."""
        removed = location.detach()
        for eid in self._walk.collect_ids(removed):
            if ws is not None:
                ws.set(eid, None)
                ws.clear_suffix(f"_{eid}")

    def _warn_unreachable_patch(
        self, scene: SceneMessage, target_id: str, scene_id: str
    ) -> None:
        """Warn when a target is present in the scene but unreachable by ``find``.

        Every id ``collect_ids`` reports must be reachable; a present-yet-
        unreachable id signals a tree-walk coverage gap, not the normal no-op of
        a truly-absent id.
        """
        present = any(
            target_id in self._walk.collect_ids(elem) for elem in scene.elements
        )
        if present:
            _log.warning(
                "patch target %r present in scene %r but unreachable by the "
                "element walk; patch not applied",
                target_id,
                scene_id,
            )

    def _apply_patch_set(
        self,
        location: ElementLocation,
        fields: dict[str, Any],
        ws: WidgetState | None = None,
        *,
        scene_id: str,
    ) -> None:
        """Apply a set-patch to a located element and sync widget state.

        Validation happens here at the boundary; the location owns the mutation
        strategy, so this method never branches on the element model. A patch is
        rejected two ways, both handled per patch so the batch continues and the
        message loop never dies: a structural error (unknown field) is skipped;
        a value error (a setter's ``ValueError``/``TypeError`` on an
        out-of-range, NaN, or wrong-typed value) is caught around ``apply_set``
        and skipped. Either way the bad patch is a clean no-op, not an uncaught
        exception.
        """
        elem = location.element
        valid, unknown = self._partition_fields(elem, fields)
        if unknown:
            self._warn_skipped(
                elem,
                scene_id,
                f"unknown field(s) {sorted(unknown)!r}; element unchanged",
            )
            return
        if valid:
            try:
                elem = location.apply_set(valid)
            except (ValueError, TypeError) as exc:
                self._warn_skipped(
                    elem,
                    scene_id,
                    f"rejected: {exc}; offending fields {valid!r}; "
                    "element keeps its previous value",
                )
                return
        self._widget_sync.sync(elem, valid, ws)

    def _partition_fields(
        self, elem: Element, fields: dict[str, Any]
    ) -> tuple[dict[str, Any], set[str]]:
        """Split a patch's fields into (ordered patchable values, unknown names).

        ``valid`` keeps the patch's insertion order so ``Element.apply_patch``
        runs the setters in the order the agent wrote them; a set intersection
        would let hash order pick a non-deterministic sequence. ``id`` and
        ``kind`` are excluded by ``_known_patch_fields``, never flagged unknown.
        """
        known = self._known_patch_fields(elem)
        valid = {name: value for name, value in fields.items() if name in known}
        unknown = fields.keys() - known - {"id", "kind"}
        return valid, unknown

    def _warn_skipped(self, elem: Element, scene_id: str, reason: str) -> None:
        """Log a set-patch skipped at the boundary; the caller then continues.

        A structural rejection (unknown field) or value rejection (setter
        ``ValueError``/``TypeError``) is surfaced per patch — diagnosable
        without aborting the batch. ``reason`` carries the offending detail.
        """
        _log.warning(
            "patch for scene %r element %r skipped: %s",
            scene_id,
            getattr(elem, "id", None),
            reason,
        )

    def _known_patch_fields(self, elem: Element) -> set[str]:
        """Return ``elem``'s patchable field names, minus the identity fields.

        ABC elements expose a ``_set_<field>`` setter per patchable field;
        legacy dataclasses expose their declared fields. ``id`` and ``kind``
        are dropped so an identity field is never applied nor flagged unknown.
        """
        if isinstance(elem, ABCElement):
            names = self._abc_setter_fields(elem)
        else:
            names = {f.name for f in dataclasses.fields(elem)}
        return names - {"id", "kind"}

    def _abc_setter_fields(self, elem: ABCElement) -> set[str]:
        """Return the field names an ABC element exposes a ``_set_`` setter for."""
        return {
            name.removeprefix("_set_")
            for name in dir(elem)
            if name.startswith("_set_") and callable(getattr(elem, name))
        }
