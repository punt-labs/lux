"""HandlerFiring -- fire an element's event on the Hub, judging what its handlers write.

A handler that runs on the Hub patches the Hub's own copy of an element, and no one
asks the agent write path about that. This fires the event inside
:class:`~punt_lux.domain.handler_writes.HandlerWrites`, so every ``apply_patch`` a
handler makes while it runs is shown to the write seam's nesting cap first: a handler
that would nest the scene past it is refused, logged with the handler's other
failures, and leaves the element as it was. It is the one Hub-side door an element's
event is fired through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.handler_writes import HandlerWrites
from punt_lux.domain.hub.field_realization import AbcFieldRealization
from punt_lux.domain.hub.write_errors import NestingExceededError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.domain.event_protocol import Event
    from punt_lux.domain.hub.write_seam import WriteSeam
    from punt_lux.domain.ids import SceneId

__all__ = ["HandlerFiring"]


@final
class HandlerFiring:
    """Fires events on the Hub's elements, under the seam's nesting cap."""

    _seam: WriteSeam
    __slots__ = ("_seam",)

    def __new__(cls, seam: WriteSeam) -> Self:
        self = super().__new__(cls)
        self._seam = seam
        return self

    def fire(self, scene_id: SceneId, element: AbcElement, event: Event) -> None:
        """Fire ``event`` on ``element``, judging every patch its handlers write first.

        A patch is measured on a copy of its target, so the element itself, and
        anything observing it, is untouched when it is refused.
        """

        def admit(target: AbcElement, patch: Mapping[str, object]) -> None:
            realization = AbcFieldRealization(target, patch)
            refusal = self._seam.nesting_refusal(scene_id, [realization])
            if refusal is not None:
                raise NestingExceededError(refusal)

        with HandlerWrites.judged(admit):
            element.fire(event)
