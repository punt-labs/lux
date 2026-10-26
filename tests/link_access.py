"""Test-only access to the parts of a ``DisplayLink`` a test must reach into.

Production hands the write seat away once and keeps generations behind opaque
references; a test that drives a link directly needs a writer on demand and, to
script a dial's socket, the generation behind its name. Both come from the link's
own private state, here and nowhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from punt_lux.domain.hub.scene_presentation import ScenePresentation
from tests.domain.display_double import until

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.hub.dial_death import DialDeath
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_link import DisplayLink
    from punt_lux.domain.hub.display_writer import DisplayWriter
    from punt_lux.protocol import Element

__all__ = ["deaths_of", "generation_of", "shown", "writer_of"]


class _Deaths(Protocol):
    """Anything that hands over the deaths it has recorded, one at a time."""

    def take_death(self) -> DialDeath | None:
        """Hand over the oldest recorded death."""
        ...


def deaths_of(source: _Deaths) -> tuple[DialDeath, ...]:
    """Drain every death ``source`` has recorded, oldest first."""
    drained: list[DialDeath] = []
    while (death := source.take_death()) is not None:
        drained.append(death)
    return tuple(drained)


def writer_of(link: DisplayLink) -> DisplayWriter:
    """A writer pinned to ``link``'s current dial, without taking the seat."""
    return link._desk._seat.current()  # test seam: production takes the seat once


def generation_of(link: DisplayLink) -> DialGeneration:
    """The generation behind ``link``'s current dial."""
    return link._connection.require()  # test seam: production holds only refs


def shown(
    link: DisplayLink,
    scene_id: str,
    elements: Sequence[Element],
    presentation: ScenePresentation | None = None,
    timeout: float = 5.0,
) -> bool:
    """Send a scene as the replicator does, then wait for the display's ack of it.

    The ack settles the dial's ledger, so the scene was taken once nothing is owed.
    A framed ``presentation`` defaults to the scene's own id, as the Hub frames one.
    """
    link.connect(listen=True)  # the ack is read by the listener; a no-op if it runs
    generation = generation_of(link)
    framed = presentation or ScenePresentation(frame_id=scene_id)
    writer_of(link).send_scene(framed.message(scene_id, list(elements)))
    return until(lambda: generation.owed_acks == 0, timeout)
