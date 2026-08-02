"""Evictions — the interactions that left the pending buffer undelivered.

An interaction the buffer evicts never reaches the Hub, so no answer for it will
come and whatever the display latched when it fired must be given up. That holds
for the last gesture on an element, but not for one a newer gesture of the same
kind has already superseded: the user toggles twice quickly, the first toggle
ages out while the second is still in flight, and reverting on the older one
would snap the widget back to the Hub's value while a live interaction is still
waiting to be answered. The newer gesture settles the element — by its answer, or
by its own eviction.

The split is taken by the buffer at the moment of eviction, while what is still
held is known. Taking it later would be wrong: delivery drains the buffer between
the eviction and the compensation, so a newer gesture sent in the same frame is
no longer held even though its answer is still outstanding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["Evictions"]

# What makes two interactions the same gesture continued: the same kind of event
# on the same element of the same scene. The scene is part of it because the
# latched state a compensation clears is per-scene widget state.
type _Gesture = tuple[str | None, str, str | None]


@final
@dataclass(frozen=True, slots=True)
class Evictions:
    """Interactions that left the buffer undelivered, and what they still owe.

    ``lost`` is every evicted interaction, in the order it was held.
    ``compensable`` is the subset whose display-side optimism must be given up:
    the last eviction of its gesture, with nothing newer outstanding to speak for
    the element.
    """

    lost: tuple[RemoteEventHandlerInvocation, ...]
    compensable: tuple[RemoteEventHandlerInvocation, ...]

    @classmethod
    def of(
        cls,
        lost: Iterable[RemoteEventHandlerInvocation],
        outstanding: Iterable[RemoteEventHandlerInvocation],
    ) -> Self:
        """Split ``lost`` against the interactions ``outstanding`` still holds.

        Walking newest first and settling one gesture at a time leaves exactly
        the last eviction of each gesture that nothing outstanding — and no later
        eviction in the same batch — already speaks for.
        """
        events = tuple(lost)
        settled: set[_Gesture] = {cls._gesture(ev) for ev in outstanding}
        compensable: list[RemoteEventHandlerInvocation] = []
        for event in reversed(events):
            gesture = cls._gesture(event)
            if gesture in settled:
                continue
            settled.add(gesture)
            compensable.append(event)
        compensable.reverse()
        return cls(events, tuple(compensable))

    def log_undeliverable(self, max_age: float) -> None:
        """Warn about what the buffer could not deliver within ``max_age``."""
        if not self.lost:
            return
        logger.warning(
            "%d interaction(s) undeliverable past the %.1fs buffer, %d compensated: %s",
            len(self.lost),
            max_age,
            len(self.compensable),
            [f"{ev.element_id}:{ev.event_kind}" for ev in self.lost],
        )

    @staticmethod
    def _gesture(event: RemoteEventHandlerInvocation) -> _Gesture:
        """Return what identifies one continuing gesture across interactions."""
        return (event.scene_id, event.element_id, event.event_kind)
