"""The display-link wire method :class:`_RestTransport` composes and delegates to.

Split from :mod:`punt_lux.client._rest_display` (one concern, one module) --
the Hub's observed link state is a discriminated read with no display round
trip, distinct from the display-proxy family that module wraps.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.display_link import (
    ConnectedLinkState,
    DisconnectedLinkState,
)
from punt_lux.rest_http_call import HttpCall
from punt_lux.rest_reply import RestReply

if TYPE_CHECKING:
    from punt_lux.operations import OpError
    from punt_lux.operations.models.display_link import DisplayLinkState
    from punt_lux.rest_transport import HttpResponse, HttpTransport

__all__ = ["_DisplayLinkRestOps"]


@final
class _DisplayLinkRestOps:
    """Wraps the ``GET /display/link`` route -- one discriminated read."""

    _transport: HttpTransport
    _headers: dict[str, str]
    __slots__ = ("_headers", "_transport")

    def __new__(cls, transport: HttpTransport, headers: dict[str, str]) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._headers = headers
        return self

    def get_link(self) -> DisplayLinkState | OpError:
        """Return the Hub's observed link state through ``GET /display/link``."""
        call = HttpCall.read("/display/link", self._headers)
        response = self._transport.request(call)
        reply = RestReply(response)
        if self._is_2xx_disconnected(response):
            return reply.read(DisconnectedLinkState)
        return reply.read(ConnectedLinkState)

    @staticmethod
    def _is_2xx_disconnected(response: HttpResponse) -> bool:
        """Peek the wire ``kind`` tag on a 2xx body, without a full validation.

        A non-2xx status (or an unparseable body) falls through to
        ``ConnectedLinkState`` -- harmless, since :meth:`RestReply.read`
        ignores its ``ok`` argument once the status is not 2xx.
        """
        if not (200 <= response.status < 300):
            return False
        try:
            body = json.loads(response.body)
        except json.JSONDecodeError:
            return False
        return isinstance(body, dict) and body.get("kind") == "disconnected"
