"""Apply a batch of update patches to a scene's element tree."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.protocol import (
    CheckboxElement,
    ComboElement,
    Element,
    InputNumberElement,
    InputTextElement,
    RadioElement,
    SelectableElement,
    SliderElement,
    WindowElement,
)

if TYPE_CHECKING:
    from punt_lux.protocol import SceneMessage, UpdateMessage
    from punt_lux.scene.element_walk import ElementLocation, SceneTreeWalk
    from punt_lux.scene.widget_state import WidgetState

_log = logging.getLogger(__name__)


@final
class PatchApplier:
    """Apply an update's patch batch to a resolved scene's element tree.

    Owns the "apply a batch of patches" responsibility split out of
    :class:`SceneManager`: locate each patch target, remove it or set fields,
    mirror value-bearing inputs into :class:`WidgetState`, and mark moved or
    resized windows dirty. The scene-lifecycle role — storing scenes, frames,
    and ownership — stays on the manager.

    Tree navigation is delegated to a shared :class:`SceneTreeWalk`; the
    dirty-windows set is the manager's own set, mutated in place so the
    rendering layer sees marked windows through ``SceneManager.dirty_windows``.
    """

    __slots__ = ("_dirty_windows", "_walk")

    _walk: SceneTreeWalk
    _dirty_windows: set[str]

    def __new__(cls, *, walk: SceneTreeWalk, dirty_windows: set[str]) -> Self:
        self = super().__new__(cls)
        self._walk = walk
        self._dirty_windows = dirty_windows
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
        """Surface a patch whose target is present but unreachable.

        Every id ``collect_ids`` reports must be reachable by ``find``; an id
        present yet unreachable signals a tree-walk coverage gap the state
        machine must not swallow. A truly-absent id is a normal no-op.
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

        Validation of unknown fields happens here (at the boundary); the
        location owns the mutation strategy (in-place ``apply_patch`` for an
        ABC element, ``dataclasses.replace`` + rebind for a legacy one), so
        this method never branches on which element model it found.

        A range-validated setter (e.g. a progress ``fraction`` outside
        ``[0, 1]``, or NaN) rejects a bad value by raising ``ValueError`` after
        restoring the prior value. That rejection is caught around the
        ``apply_set`` call, logged, and skipped: one bad patch is a clean no-op
        — the element keeps its previous valid value — instead of unwinding into
        the ``apply`` loop and out to the message loop, where an uncaught
        ``ValueError`` would terminate the display process. Future
        range-validated kinds (slider, input_number) rely on this same guard.
        The catch is scoped to ``apply_set`` alone so the unknown-field
        ``ValueError`` above — a structural, not value, error — still propagates.
        """
        elem = location.element
        known = self._known_patch_fields(elem)
        valid = {
            k: v for k, v in fields.items() if k not in ("id", "kind") and k in known
        }
        unknown = fields.keys() - {"id", "kind"} - valid.keys()
        if unknown:
            element_id = getattr(elem, "id", None)
            msg = (
                f"patch for scene {scene_id!r} element {element_id!r} "
                f"contains unknown fields: {sorted(unknown)}"
            )
            raise ValueError(msg)
        if valid:
            try:
                elem = location.apply_set(valid)
            except ValueError as exc:
                self._warn_rejected_patch(elem, valid, scene_id, exc)
                return
        self._sync_widget_state(elem, valid, ws)

    def _warn_rejected_patch(
        self,
        elem: Element,
        fields: dict[str, Any],
        scene_id: str,
        exc: ValueError,
    ) -> None:
        """Log a set-patch a validated setter rejected; the caller then skips it.

        Names the scene, the element, the offending fields, and the setter's
        message so the rejection stays diagnosable — mirroring the
        unreachable-patch warning — without the ``ValueError`` aborting the
        patch batch or reaching the display's message loop.
        """
        _log.warning(
            "patch for scene %r element %r rejected: %s; offending fields %r; "
            "element keeps its previous value",
            scene_id,
            getattr(elem, "id", None),
            exc,
            fields,
        )

    def _known_patch_fields(self, elem: Element) -> set[str]:
        """Return the patchable field names for ``elem``.

        ABC elements expose a ``_set_<field>`` setter per patchable field;
        legacy dataclasses expose their declared fields.
        """
        if isinstance(elem, ABCElement):
            return {
                name.removeprefix("_set_")
                for name in dir(elem)
                if name.startswith("_set_") and callable(getattr(elem, name))
            }
        return {f.name for f in dataclasses.fields(elem)}

    def _sync_widget_state(
        self, elem: Element, valid: dict[str, Any], ws: WidgetState | None
    ) -> None:
        """Mirror a post-patch element's value into WidgetState.

        A value-bearing input writes its new ``widget_value()``; a kind
        excluded from that dispatch (e.g. ColorPickerElement) has its cache
        DISCARDED so the next render re-seeds from the patched fields rather
        than reading a poisoned ``None``. A moved/resized window is marked
        dirty so its next frame re-applies position.
        """
        eid = getattr(elem, "id", None)
        has_value_key = valid.keys() & {"value", "selected", "items"}
        if eid is not None and ws is not None and has_value_key:
            new_value = self._widget_value(elem)
            if new_value is None:
                ws.discard(eid)
            else:
                ws.set(eid, new_value)
        has_pos_key = valid.keys() & {"x", "y", "width", "height"}
        if eid is not None and isinstance(elem, WindowElement) and has_pos_key:
            self._dirty_windows.add(eid)

    def _widget_value(self, elem: Element) -> Any:
        """Extract the current widget value from an element for WidgetState.

        Direct ``isinstance`` dispatch against the seven value-bearing input
        element classes — each owns a ``widget_value()`` method that returns
        the field ``SceneManager`` mirrors into ``WidgetState`` after a patch.
        ``ColorPickerElement`` is intentionally excluded: its renderer seeds
        ``WidgetState`` with an ``ImVec4`` via ``ensure()``, so returning the
        raw hex string here would corrupt that state.
        """
        if isinstance(
            elem,
            (
                CheckboxElement,
                ComboElement,
                InputNumberElement,
                InputTextElement,
                RadioElement,
                SelectableElement,
                SliderElement,
            ),
        ):
            return elem.widget_value()
        return None
