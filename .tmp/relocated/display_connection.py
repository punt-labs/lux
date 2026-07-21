"""HubDisplayConnection — luxd's one display connection behind the DisplayPort.

The concrete adapter the operations layer proxies display facts through. It wraps
the two Hub-side collaborators a proxied read or write needs: a liveness check,
so a query short-circuits when no display is running, and the connection
registry, whose reconnect-once policy already bounds a send. Every outcome is
folded into a :class:`DisplayReply` so the operation never sees a socket.
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
    """Proxy display queries over the Hub's one connection, bounded and healed."""

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
        raises ``OSError`` within the limit, and the dead connection is dropped so
        the next call reconnects. A ``None`` reply is the receive-side timeout.
        """
        if not self._is_running():
            return DisplayFault(code="display_unavailable")
        try:
            response = self._clients.get().query(method, dict(params))
        except OSError:
            self._clients.drop()
            return DisplayFault(code="timeout")
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
        if pong is None:
            return DisplayFault(code="timeout")
        # A pong echoes the ts we sent, so the round-trip time is always known;
        # a pong without one (a defensive display path) reports a zero elapsed.
        rtt = now - pong.ts if pong.ts is not None else 0.0
        return DisplayReplied(payload={"rtt_seconds": rtt})
