"""DisplayRequests -- what the Hub asks the display, pinned to one dial.

A port is made for the dial that was current when it was made, and every request
through it goes out on that dial and no other: a redial between two requests fails
the second with the error of the dial it was made for, instead of quietly going out
on the new one. So a failure always names the dial it happened on (:attr:`dial`),
and whoever must drop a dead dial drops that one and never its successor.

A ping and a query each send one request and wait for the one reply it elicits. The
reply carries no request id, so what keeps replies and requests together is order
and exclusion (see :class:`~punt_lux.domain.hub.request_exchange.RequestExchange`).
A liveness ping never queues behind a query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.protocol import PongMessage, QueryRequest, QueryResponse

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.request_exchange import RequestExchange

__all__ = ["DisplayRequests"]


@final
class DisplayRequests:
    """Ask the display, on the one dial this port was made for."""

    _generation: DialGeneration
    _exchange: RequestExchange
    __slots__ = ("_exchange", "_generation")

    def __new__(cls, generation: DialGeneration, exchange: RequestExchange) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        self._exchange = exchange
        return self

    @classmethod
    def pinned(cls, exchange: RequestExchange) -> Self:
        """A port pinned to the dial that is current now.

        Raises the error that says why there is none (see
        :meth:`~punt_lux.domain.hub.display_connection.DisplayConnection.require`).
        """
        return cls(exchange.current(), exchange)

    @property
    def dial(self) -> DialRef:
        """The dial every request through this port uses: what a failure names."""
        return self._generation.ref

    def probe_alive(self, timeout: float) -> bool:
        """Whether the display is alive, as a liveness check counts it.

        A ping already in flight is itself probing the display, so finding the dial
        busy is no evidence of a dead one: it counts as alive. This is the one place
        that rule lives; a caller that needs proof of a scene asks :meth:`await_acks`.

        Bytes that moved on the socket in either direction within ``D``, sends
        included, are liveness too, and judging that needs no lock: the keepalive gives
        an unresponsive verdict only after ``D`` of silence, and then by a ping that
        goes unanswered. The look is made before the ping is sent, so its own bytes
        cannot vouch for the ping's answer.
        """
        if self._generation.is_progressing():
            return True
        try:
            return self.ping(timeout) is not None
        except DisplayBusyError:
            return True

    def await_acks(self, timeout: float) -> bool:
        """Whether the display acked every scene written to this dial in ``timeout``.

        The isolation loop's proof that the display survived the scene it was just
        sent, before the next one goes out. An ack is sent only after a swap that
        completed with the scene installed, so it is the one answer that says so; a
        pong says only that the display is reading. ``False`` is a display that
        stalled or died holding the scene. Raises :class:`DisplayBusyError` if another
        wait for acks held the dial for the whole lock-wait budget.
        """
        with self._exchange.exclusive("ack", timeout):
            pending = self._generation.expect_drained()
            if pending is None:
                return True
            return self._exchange.answer(self._generation, pending, timeout) is not None

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        """Ping the display; its pong, or ``None`` if none came in time.

        Raises :class:`DisplayBusyError` if another ping held the dial for the
        whole lock-wait budget: nothing was sent, so nothing is known of the
        display. A ping that times out keeps its dial: a late pong is dropped,
        never matched to the next ping, whose ``ts`` differs.
        """
        with self._exchange.exclusive("ping", timeout) as ts:
            pending = self._generation.send_ping(ts)
            return self._exchange.answer(self._generation, pending, timeout)

    def query(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> QueryResponse | None:
        """Send a generic query and wait for the response; ``None`` on a timeout.

        A query may ask the display to change its own frame visibility
        (``set_frame_state``): that is Display-owned state, not Hub scene content, so
        the Hub's single-writer rule does not cover it.

        Nothing on the wire says which query a response answers, so a query that
        times out retires its dial: the response, if it ever comes, can no longer
        be taken for the next query's. Raises :class:`DisplayBusyError` if another
        query held the dial for the whole lock-wait budget; nothing was sent and
        the dial is untouched.
        """
        request = QueryRequest(method=method, params=params or {})
        with self._exchange.exclusive("query", timeout):
            pending = self._generation.send_query(request)
            response = self._exchange.answer(self._generation, pending, timeout)
            if response is None:
                self._exchange.give_up(self._generation)
            return response
