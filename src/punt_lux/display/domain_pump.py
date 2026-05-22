"""Dual-write pump: route wire SceneMessages through the domain Display.

This module is the transitional bridge between the legacy SceneManager
path and the authoritative domain ``Display`` introduced in PR 1.  For
every basics-only scene that arrives over the wire, the pump removes any
elements the domain Display already holds for the scene and re-adds the
current set so the snapshot reflects the latest send.  Mixed-kind scenes
(containing any non-basics element) bypass the pump until their families
migrate.

Failures from ``Display.apply`` — ``OwnershipError``, ``DuplicateIdError``,
``PropertyTypeError`` — are surfaced via ``logger.warning`` with full
context (scene_id, element_id, op, error kind).  Silently dropping them
would let SceneManager and the domain Display diverge.
"""

from __future__ import annotations

import logging
from typing import Self, cast

from punt_lux.domain.display import Display, Result
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.event import ElementAdded, ElementRemoved, ElementUpdated
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement
from punt_lux.protocol import SceneMessage

__all__ = ["DomainPump"]

_log = logging.getLogger(__name__)


class DomainPump:
    """Mirror basics-only SceneMessages into a domain Display.

    The pump owns the per-hub ``ClientId`` and the membership predicate
    that decides which kinds are routed.  Tests can construct one with a
    fresh ``Display`` and exercise routing in isolation — no socket, no
    ImGui.
    """

    _display: Display
    _client_id: ClientId
    _basics_kinds: tuple[type, ...]

    def __new__(
        cls,
        display: Display,
        client_id: ClientId,
        basics_kinds: tuple[type, ...],
    ) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._client_id = client_id
        self._basics_kinds = basics_kinds
        return self

    def route(self, msg: SceneMessage) -> None:
        """Route a SceneMessage through the domain Display if it qualifies."""
        if not msg.elements:
            return
        # Mixed-scene rule: any non-basics element disqualifies the whole
        # scene from the new path.
        if any(not isinstance(elem, self._basics_kinds) for elem in msg.elements):
            return
        scene_id = SceneId(msg.id)
        self._display.add_scene(scene_id)
        self._clear_scene(scene_id)
        for elem in msg.elements:
            # cast: isinstance check above narrowed the element to a basics
            # kind, every one of which satisfies the domain Element Protocol.
            result = self._display.apply(
                self._client_id,
                AddElement(
                    scene_id=scene_id,
                    element=cast("DomainElement", elem),
                    parent_id=None,
                ),
            )
            _warn_on_error(
                result, scene_id=scene_id, element_id=ElementId(elem.id), op="add"
            )

    def _clear_scene(self, scene_id: SceneId) -> None:
        """Remove every element this hub owns in the given domain scene."""
        try:
            snap = self._display.snapshot(scene_id)
        except KeyError:
            return
        for element_id in snap.element_ids:
            result = self._display.apply(
                self._client_id,
                RemoveElement(scene_id=scene_id, element_id=element_id),
            )
            _warn_on_error(
                result, scene_id=scene_id, element_id=element_id, op="remove"
            )


def _warn_on_error(
    result: Result,
    *,
    scene_id: SceneId,
    element_id: ElementId,
    op: str,
) -> None:
    """Log a domain Display.apply failure with full context."""
    # Event is the success-shape; anything else is a typed Error from the
    # domain.error module.  Use the concrete success classes (the ``Event``
    # type alias is not isinstance-checkable).
    if isinstance(result, ElementAdded | ElementRemoved | ElementUpdated):
        return
    _log.warning(
        "domain Display.apply refused %s(scene=%s, element=%s): %s — %r",
        op,
        scene_id,
        element_id,
        result.kind,
        result,
    )
