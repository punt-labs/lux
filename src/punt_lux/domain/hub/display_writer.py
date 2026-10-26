"""DisplayWriter -- the one way anything is written to the display, pinned to a dial.

Writing to the display is the replicator's act alone: every other part of the Hub
writes the store and marks a scene dirty. That is made a matter of what exists, not
of who calls what. The write verbs live on this class and nowhere else; an instance
is made only by a :class:`WriteSeat`; the seat is made once, by the link, and given
away once (:meth:`~punt_lux.domain.hub.request_desk.RequestDesk.take_seat`), so
there is one holder and a second asker is refused. The one write the link makes for
itself, the manifest that declares what the Hub holds when a connection opens, is the
request desk's and is not a verb of any writer.

A writer is pinned to the dial that was current when it was made, and every write
goes out on that dial: a failure names it (:attr:`dial`), and a redial in between
fails the next write instead of letting it land on the new dial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import CallbackMenuMessage, MenuMessage

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.request_exchange import RequestExchange
    from punt_lux.protocol import SceneMessage

__all__ = ["DisplayWriter", "WriteSeat"]


@final
class DisplayWriter:
    """Write to the display, on the one dial this writer was made for."""

    _generation: DialGeneration
    _exchange: RequestExchange
    __slots__ = ("_exchange", "_generation")

    def __new__(cls, generation: DialGeneration, exchange: RequestExchange) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        self._exchange = exchange
        return self

    @property
    def dial(self) -> DialRef:
        """The dial every write through this writer uses: what a failure names."""
        return self._generation.ref

    def send_scene(self, message: SceneMessage) -> None:
        """Send a built scene without waiting for an ack.

        The ack is still owed, and is matched and dropped when it arrives.
        """
        self._generation.send_scene(message)

    def set_menu(self, menus: list[dict[str, object]]) -> None:
        """Set custom menu bar entries."""
        self._generation.send(MenuMessage(menus=menus))

    def set_callback_menus(self, submenus: list[dict[str, object]]) -> None:
        """Replace the display's Clients menu (Hub-composed)."""
        self._generation.send(CallbackMenuMessage(submenus=submenus))


@final
class WriteSeat:
    """Where writers are made: the one place that can, handed out once."""

    _exchange: RequestExchange
    __slots__ = ("_exchange",)

    def __new__(cls, exchange: RequestExchange) -> Self:
        self = super().__new__(cls)
        self._exchange = exchange
        return self

    def current(self) -> DisplayWriter:
        """A writer pinned to the dial that is current now.

        Raises the error that says why there is none (see
        :meth:`~punt_lux.domain.hub.display_connection.DisplayConnection.require`).
        """
        return DisplayWriter(self._exchange.current(), self._exchange)
