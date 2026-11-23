"""Resolve a pinned Display query, retaining the Hub dial's identity for facts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.hub.connection_closed import ConnectionClosedError
from punt_lux.hub.display_busy import DisplayBusyError
from punt_lux.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.hub.clients import ClientRegistry
    from punt_lux.hub.display_requests import DisplayRequests
    from punt_lux.operations.display_reply import DisplayReply


class DisplayQuery:
    """Turn one pinned query into an operation reply without redialing."""

    @staticmethod
    def exchange[T](
        clients: ClientRegistry, call: Callable[[DisplayRequests], T]
    ) -> T | DisplayFault:
        """Pin before calling; a failure retires only the dial that failed."""
        try:
            port = clients.asks()
        except (DisplayNotConnectedError, ConnectionClosedError):
            return DisplayFault(code="display_unavailable")
        except OSError:
            return DisplayFault(code="timeout")
        try:
            return call(port)
        except DisplayBusyError:
            return DisplayFault(code="timeout")
        except ConnectionClosedError:
            clients.drop(port.dial)
            return DisplayFault(code="display_unavailable")
        except OSError:
            clients.drop(port.dial)
            return DisplayFault(code="timeout")

    @staticmethod
    def run(
        port: DisplayRequests, method: str, params: Mapping[str, object]
    ) -> DisplayReply:
        response = port.query(method, dict(params))
        if response is None:
            return DisplayFault(code="timeout")
        if response.error:
            return DisplayErrored(message=response.error)
        payload = response.result
        if method == "get_display_info":
            payload = {**payload, "hub_connection_id": str(port.dial)}
        return DisplayReplied(payload=payload)
