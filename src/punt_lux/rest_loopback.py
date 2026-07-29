"""The production HTTP transport: one loopback round-trip to luxd.

The one shipped implementation of the :mod:`punt_lux.rest_transport` contract, in
its own module so the urllib socket work stays out of the contract and client.
"""

from __future__ import annotations

import http.client
from typing import TYPE_CHECKING, Self, final

from punt_lux.rest_transport import HttpResponse, HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.rest_http_call import HttpCall

__all__ = ["LoopbackTransport"]


@final
class LoopbackTransport:
    """The production transport: one loopback HTTP round-trip with one timeout.

    A non-2xx reply from a reachable luxd is a result — status and body in an
    :class:`HttpResponse`; only an unreachable or stalled luxd raises
    :class:`HubUnavailableError`. There is no retry: a loopback stall means luxd is
    down, not busy.
    """

    _port: int
    _timeout: float
    __slots__ = ("_port", "_timeout")

    def __new__(cls, port: int, timeout: float) -> Self:
        self = super().__new__(cls)
        self._port = port
        self._timeout = timeout
        return self

    def request(self, call: HttpCall) -> HttpResponse:
        conn = http.client.HTTPConnection(
            "127.0.0.1", self._port, timeout=self._timeout
        )
        try:
            headers = call.wire_headers()
            conn.request(call.method, call.path, body=call.body, headers=headers)
            response = conn.getresponse()
            return HttpResponse(status=response.status, body=response.read())
        except (OSError, http.client.HTTPException) as exc:
            raise HubUnavailableError(
                f"luxd is not reachable on port {self._port} — {exc}"
            ) from exc
        finally:
            conn.close()
