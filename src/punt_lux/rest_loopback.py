"""The production HTTP transport: one loopback round-trip to luxd.

The transport contract lives in :mod:`punt_lux.rest_transport`; this is its one
shipped implementation, the urllib round-trip the CLI's REST client uses. A test
substitutes its own transport, so keeping the concrete socket work in its own
module leaves both the contract and the typed client free of wire detail.
"""

from __future__ import annotations

import http.client
from typing import Self, final

from punt_lux.rest_transport import HttpResponse, HubUnavailableError

__all__ = ["LoopbackTransport"]


@final
class LoopbackTransport:
    """The production transport: one loopback HTTP round-trip with one timeout.

    A non-2xx reply from a reachable luxd is a result, not a failure — the status
    and body come back as an :class:`HttpResponse`; only an unreachable or stalled
    luxd raises :class:`HubUnavailableError`. There is no retry — the budget for a
    loopback call is milliseconds, and a stall means luxd is down, not busy.
    """

    _port: int
    _timeout: float
    __slots__ = ("_port", "_timeout")

    def __new__(cls, port: int, timeout: float) -> Self:
        self = super().__new__(cls)
        self._port = port
        self._timeout = timeout
        return self

    def request(self, method: str, path: str, body: bytes | None) -> HttpResponse:
        conn = http.client.HTTPConnection(
            "127.0.0.1", self._port, timeout=self._timeout
        )
        headers = {"Content-Type": "application/json"} if body is not None else {}
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return HttpResponse(status=response.status, body=response.read())
        except (OSError, http.client.HTTPException) as exc:
            raise HubUnavailableError(
                f"luxd is not reachable on port {self._port} — {exc}"
            ) from exc
        finally:
            conn.close()
