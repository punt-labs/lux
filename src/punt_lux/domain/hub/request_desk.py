"""RequestDesk -- where a link's requests are made: its asks, and the seat for writes.

One desk belongs to one link and is reachable only through it. It builds the exchange
every request port shares, makes the ask port for the dial that is current when asked,
and holds the one seat writers are made at. The seat is built here and nowhere else, and so is the manifest the link writes for
itself when a connection opens: no writer has a verb for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_replies import DisplayReplies
from punt_lux.domain.hub.display_requests import DisplayRequests
from punt_lux.domain.hub.display_writer import WriteSeat
from punt_lux.domain.hub.request_exchange import RequestExchange
from punt_lux.protocol import HubManifestMessage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.domain.hub.display_listener import DisplayListener

__all__ = ["RequestDesk"]


@final
class RequestDesk:
    """The ask port for the current dial, and the one write seat."""

    _exchange: RequestExchange
    _seat: WriteSeat
    _seat_taken: bool
    __slots__ = ("_exchange", "_seat", "_seat_taken")

    def __new__(
        cls, connection: DisplayConnection, listener: DisplayListener, budget: float
    ) -> Self:
        self = super().__new__(cls)
        self._exchange = RequestExchange(
            connection, DisplayReplies(connection, listener), budget
        )
        self._seat = WriteSeat(self._exchange)
        self._seat_taken = False
        return self

    def take_seat(self) -> WriteSeat:
        """Hand over the seat writers are made at, once: its holder is the one writer.

        Raises ``ValueError`` on a second ask, so no second part of the Hub can be
        given the power to write to the display.
        """
        if self._seat_taken:
            msg = "the display's write seat was already handed to a writer"
            raise ValueError(msg)
        self._seat_taken = True
        return self._seat

    def declare(self, scene_ids: Sequence[str]) -> None:
        """Write the manifest that declares what the Hub holds (DES-068).

        The one write the link makes for itself, as the second half of opening a
        connection (``DisplayLink.open_as_hub``); it does not take the seat.
        """
        manifest = HubManifestMessage(scene_ids=tuple(scene_ids))
        self._exchange.current().send(manifest)

    def asks(self) -> DisplayRequests:
        """An ask port pinned to the dial that is current now.

        Raises the error that says why there is none (see
        :meth:`~punt_lux.domain.hub.display_connection.DisplayConnection.require`).
        """
        return DisplayRequests.pinned(self._exchange)
