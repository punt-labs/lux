"""ElementInvocationResolver — resolve a display invocation to a fireable Element.

The scene-element leg of ``HubInteractionDispatch`` guards a handful of ways
a click can be stale or malformed before it may fire: a missing scene id, an
element the Hub no longer indexes, a non-ABC (legacy) element, or a click on
a descendant of an ancestor the Hub already dismissed. Each guard is a
distinct reason to drop the invocation and never fire it; bundling the walk
here keeps the dispatch's own method to the fire-or-drop decision, not the
resolution mechanics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ElementId, SceneId

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["ElementInvocationResolver", "ResolvedInteraction"]


@dataclass(frozen=True, slots=True)
class ResolvedInteraction:
    """A display invocation resolved to a fireable Element and its owner."""

    element: AbcElement
    owner: ConnectionId
    scene_id: SceneId


@final
class ElementInvocationResolver:
    """Resolve one ``RemoteEventHandlerInvocation`` against a ``HubDisplay``."""

    _hub_display: HubDisplay
    __slots__ = ("_hub_display",)

    def __new__(cls, hub_display: HubDisplay) -> Self:
        self = super().__new__(cls)
        self._hub_display = hub_display
        return self

    def resolve(self, msg: RemoteEventHandlerInvocation) -> ResolvedInteraction | None:
        """Return the fireable element for ``msg``, or ``None`` to drop it.

        Every drop reason is logged here, so the dispatch's own method reads
        as the fire-or-drop decision, not the guard chain.
        """
        scene_id = msg.scene_id
        element_id = msg.element_id
        if scene_id is None:
            logger.warning(
                "hub dispatch missing scene_id for element_id=%s", element_id
            )
            return None
        sid = SceneId(scene_id)
        eid = ElementId(element_id)
        try:
            element = self._hub_display.resolve(sid, eid)
            owner = self._hub_display.owner_of(sid, eid)
        except (KeyError, LookupError) as exc:
            logger.warning(
                "hub dispatch resolve failed scene_id=%s element_id=%s: %s",
                scene_id,
                element_id,
                exc,
            )
            return None
        if not isinstance(element, AbcElement):
            logger.warning(
                "hub dispatch type mismatch element_id=%s type=%s",
                element_id,
                type(element).__name__,
            )
            return None
        dismissed = self._hub_display.dismissal.nearest_dismissed(sid, eid)
        if dismissed is not None:
            logger.warning(
                "hub dispatch dropped for dismissed ancestor element_id=%s "
                "dismissed_id=%s",
                element_id,
                dismissed,
            )
            return None
        return ResolvedInteraction(element=element, owner=owner, scene_id=sid)
