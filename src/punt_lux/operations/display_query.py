"""Resolve a pinned Display query, retaining the Hub dial's identity for facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.hub.connection_closed import ConnectionClosedError
from punt_lux.hub.display_busy import DisplayBusyError
from punt_lux.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)
from punt_lux.wire.operations.hub_connection import HubConnection

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.hub.clients import ClientRegistry
    from punt_lux.hub.display_requests import DisplayRequests
    from punt_lux.operations.display_reply import DisplayReply


class DisplayQuery:
    """Turn one pinned query into an operation reply without redialing."""

    _clients: ClientRegistry

    def __new__(cls, clients: ClientRegistry) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        return self

    def exchange[T](self, call: Callable[[DisplayRequests], T]) -> T | DisplayFault:
        """Pin before calling; a failure retires only the dial that failed."""
        try:
            port = self._clients.asks()
        except (DisplayNotConnectedError, ConnectionClosedError):
            return DisplayFault.UNAVAILABLE
        except OSError:
            return DisplayFault.TIMEOUT
        try:
            return call(port)
        except (DisplayBusyError, ConnectionClosedError, OSError) as error:
            if not isinstance(error, DisplayBusyError):
                self._clients.drop(port.dial)
            return (
                DisplayFault.UNAVAILABLE
                if isinstance(error, ConnectionClosedError)
                else DisplayFault.TIMEOUT
            )

    @staticmethod
    def run(
        port: DisplayRequests, method: str, params: Mapping[str, object]
    ) -> DisplayReply:
        reply = port.query(method, dict(params))
        if reply is None:
            return DisplayFault.TIMEOUT
        if reply.error:
            return DisplayErrored(message=reply.error)
        return DisplayReplied(reply.result, HubConnection.observed(port.connection_id))
