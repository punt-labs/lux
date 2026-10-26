"""Test-only access to the parts of a ``DisplayLink`` a test must reach into.

Production hands the write seat away once and keeps generations behind opaque
references; a test that drives a link directly needs a writer on demand and, to
script a dial's socket, the generation behind its name. Both come from the link's
own private state, here and nowhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.replicator_ports import DeathQueuePort
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from tests.domain.display_double import until

if TYPE_CHECKING:
    import socket
    from collections.abc import Sequence

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_death import DialDeath
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.domain.hub.display_writer import DisplayWriter
    from punt_lux.domain.hub.reader_slot import ReaderSlot
    from punt_lux.protocol import Element, Message

__all__ = [
    "bare_connection",
    "deaths_of",
    "drop_route",
    "generation_of",
    "no_reader",
    "reading_of",
    "shown",
    "socket_of",
    "writer_of",
]


def no_reader(_generation: DialGeneration, _cause: RetireCause) -> None:
    """The ask a connection is given by a test that settles nothing itself."""


def drop_route(_generation: DialGeneration, _message: Message) -> None:
    """The route of a bare connection's settle: what a dial still holds is dropped."""


def bare_connection(dialer: DisplayDialer, connect_timeout: float) -> DisplayConnection:
    """A connection with no listener, whose ended dials are settled by the asker.

    Production hands an ended dial to its reader slot; a bare connection has no
    listener, so its asker takes the free slot and settles the dial on the spot,
    which is what a library link without a reader does.
    """
    box: list[DisplayConnection] = []

    def ask(generation: DialGeneration, cause: RetireCause) -> None:
        slot = box[0].reading(generation)
        if slot is not None:
            slot.ask_settle(drop_route, cause, may_wait=True)

    connection = DisplayConnection(dialer, connect_timeout, ask_settle=ask)
    box.append(connection)
    return connection


def deaths_of(
    source: ClientRegistry | DisplayLink | DisplayConnection | DeathQueuePort,
) -> tuple[DialDeath, ...]:
    """Drain every death ``source`` has recorded, oldest first.

    Production hands the queue out once, to the charger; a test reads the same queue
    through the private state of whatever holds it, here and nowhere else.
    """
    if isinstance(source, ClientRegistry):
        client = source._client  # test seam: the registry's private link
        assert client is not None, "the registry has no link, so no death"
        source = client
    if isinstance(source, DisplayLink):
        source = source._connection  # test seam: production holds only the queue
    queue: DeathQueuePort = (
        source._suspects.deaths  # test seam: the connection's own book
        if isinstance(source, DisplayConnection)
        else source
    )
    drained: list[DialDeath] = []
    while (death := queue.take()) is not None:
        drained.append(death)
    return tuple(drained)


def reading_of(source: DisplayLink | DisplayConnection) -> ReaderSlot:
    """Who reads the current dial of ``source``: the slot its connection lends."""
    connection = source._connection if isinstance(source, DisplayLink) else source
    slot = connection.reading(connection.require())
    assert slot is not None, "the dial just asked for is not current"
    return slot


def writer_of(link: DisplayLink) -> DisplayWriter:
    """A writer pinned to ``link``'s current dial, without taking the seat."""
    return link._desk._seat.current()  # test seam: production takes the seat once


def generation_of(link: DisplayLink) -> DialGeneration:
    """The generation behind ``link``'s current dial."""
    return link._connection.require()  # test seam: production holds only refs


def socket_of(link: DisplayLink) -> socket.socket:
    """The raw socket behind ``link``'s current dial: for a test of the wire itself."""
    return generation_of(
        link
    )._socket._dial.sock  # test seam: production never lends it


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
