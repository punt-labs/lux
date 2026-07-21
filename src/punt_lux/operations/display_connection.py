"""HubDisplayConnection — luxd's one display connection behind the DisplayPort.

The concrete adapter the operations layer proxies display facts through. It lives
in the operations layer (it produces the operations' :class:`DisplayReply`) and
reaches down into the Hub for its two collaborators — a liveness check, so a
query short-circuits when no display is running, and the connection registry that
owns the socket — keeping the one dependency arrow pointing operations → domain.

There is no intra-call retry: a failed round-trip drops the dead connection and
returns a typed fault, and the next call reconnects. That mirrors the
replicator's drop-then-reconnect discipline and keeps every call bounded. Every
outcome is folded into a :class:`DisplayReply` so the operation never sees a
socket or an exception.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.hub.clients import ClientRegistry
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
        raises ``OSError`` within the limit. Reconnecting can itself fail — the
        display can die between the liveness check and ``get``, so ``connect``
        raises ``RuntimeError`` — and that is the same "no display" fault. Either
        way the dead connection is dropped so the next call reconnects, and a
        ``None`` reply is the receive-side timeout.
        """
        if not self._is_running():
            return DisplayFault(code="display_unavailable")
        try:
            response = self._clients.get().query(method, dict(params))
        except OSError:
            self._clients.drop()
            return DisplayFault(code="timeout")
        except RuntimeError:
            self._clients.drop()
            return DisplayFault(code="display_unavailable")
        if response is None:
            return DisplayFault(code="timeout")
        if response.error:
            return DisplayErrored(message=response.error)
        return DisplayReplied(payload=response.result)

    def ping(self, *, now: float) -> DisplayReply:
        """Round-trip a ping; a reply carries the elapsed ``rtt_seconds``."""
        if not self._is_running():
            return DisplayFault(code="display_unavailable")
        try:
            pong = self._clients.get().ping()
        except OSError:
            self._clients.drop()
            return DisplayFault(code="timeout")
        except RuntimeError:
            self._clients.drop()
            return DisplayFault(code="display_unavailable")
        if pong is None:
            return DisplayFault(code="timeout")
        if pong.ts is None:
            # A pong must echo the ts we sent; one without it is a defective reply,
            # not a zero-latency success — surface it as an error, never 0.0s.
            return DisplayErrored(message="pong carried no timestamp")
        return DisplayReplied(payload={"rtt_seconds": now - pong.ts})
