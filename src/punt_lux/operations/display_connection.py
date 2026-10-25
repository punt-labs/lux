"""HubDisplayConnection — luxd's one display connection behind the DisplayPort.

The concrete adapter the operations layer proxies display facts through. It
reaches into the Hub for a liveness check (so a query short-circuits when no
display is running) and the connection registry that owns the socket, keeping
the one dependency arrow pointing operations -> domain.

There is no intra-call retry: a failed round-trip drops the dial it failed on
and returns a typed fault, mirroring the replicator's drop-then-reconnect
discipline. Every outcome folds into a :class:`DisplayReply`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.hub.clients import ClientRegistry
    from punt_lux.domain.hub.display_requests import DisplayRequests
    from punt_lux.operations.display_reply import DisplayReply

__all__ = ["HubDisplayConnection"]


@final
class HubDisplayConnection:
    """Proxy display queries over the Hub's one connection, bounded and typed."""

    _is_running: Callable[[], bool]
    _clients: ClientRegistry
    __slots__ = ("_clients", "_is_running")

    def __new__(
        cls, *, is_running: Callable[[], bool], clients: ClientRegistry
    ) -> Self:
        self = super().__new__(cls)
        self._is_running = is_running
        self._clients = clients
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        """Proxy a query over one bounded attempt; never raise, never hang.

        The socket's send timeout bounds the round-trip: a wedged or dead peer
        raises ``OSError`` within the limit. Reconnecting can itself fail -- the
        display can die between the liveness check and ``get`` -- and that is the
        same "no display" fault. A failed round trip drops only the dial it was
        made on, so the next call reconnects; a ``None`` reply is the receive-side
        timeout, and so is a request that lost the lock to another of its kind.
        """
        if not self._is_running():
            return DisplayFault(code="display_unavailable")
        outcome = self._round_trip(lambda port: port.query(method, dict(params)))
        if isinstance(outcome, DisplayFault):
            return outcome
        if outcome is None:
            return DisplayFault(code="timeout")
        if outcome.error:
            return DisplayErrored(message=outcome.error)
        return DisplayReplied(payload=outcome.result)

    def ping(self, wait: float | None) -> DisplayReply:
        """Round-trip a ping bounded by ``wait`` seconds; return the rtt.

        ``wait`` of ``None`` uses the client's standing recv budget. The
        connection times the whole round trip itself with one monotonic
        clock; the pong's echoed ``ts`` is kept only as a validity signal.
        """
        if not self._is_running():
            return DisplayFault(code="display_unavailable")
        started = time.monotonic()
        outcome = self._round_trip(lambda port: port.ping(timeout=wait))
        elapsed = time.monotonic() - started
        if isinstance(outcome, DisplayFault):
            return outcome
        if outcome is None:
            return DisplayFault(code="timeout")
        if outcome.ts is None:
            # A pong must echo the ts we sent; one without it is a defective reply,
            # not a zero-latency success — surface it as an error, never 0.0s.
            return DisplayErrored(message="pong carried no timestamp")
        return DisplayReplied(payload={"rtt_seconds": elapsed})

    def _round_trip[T](self, call: Callable[[DisplayRequests], T]) -> T | DisplayFault:
        """Run ``call`` on the connected link; fold every failure into a fault.

        A failure drops the dial the call was made on and no other: by the time
        it is seen another thread may have redialed, and that dial did not fail.
        A request that lost the lock to another of its kind (nothing was sent)
        drops nothing; any other ``RuntimeError`` is a bug and propagates.
        """
        try:
            link = self._clients.get()
            dial = link.dial
        except (DisplayNotConnectedError, ConnectionClosedError):
            return DisplayFault(code="display_unavailable")
        except OSError:
            return DisplayFault(code="timeout")
        try:
            return call(link.requests)
        except DisplayBusyError:
            return DisplayFault(code="timeout")  # nothing sent; the dial is sound
        except ConnectionClosedError:
            self._clients.drop(dial)
            return DisplayFault(code="display_unavailable")
        except OSError:
            self._clients.drop(dial)
            return DisplayFault(code="timeout")

    @property
    def is_connected(self) -> bool:
        """Report a live display connection, delegating to the registry."""
        return self._clients.is_connected
