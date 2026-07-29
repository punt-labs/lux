"""The HTTP transport contract the CLI's REST client speaks over.

One round-trip, one reply value, one failure. Isolating the contract lets a test
substitute a transport routed into a ``TestClient`` while the shipped client uses
urllib, and keeps the client free of any wire concern beyond send-and-read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from punt_lux.rest_http_call import HttpCall

__all__ = ["HttpResponse", "HttpTransport", "HubUnavailableError"]


class HubUnavailableError(Exception):
    """luxd could not be reached: no port file, a refused connection, or a stall.

    Carries a single actionable sentence the CLI prints before exiting non-zero.
    """


class HttpResponse(BaseModel):
    """One HTTP reply from a reachable luxd: the status and the raw body."""

    model_config = ConfigDict(frozen=True)

    status: int
    body: bytes


class HttpTransport(Protocol):
    """The one HTTP round-trip the client needs, so tests can substitute one.

    The transport owns the endpoint; the client hands it one :class:`HttpCall` —
    verb, target, body, and the caller's identity headers — to send.
    """

    def request(self, call: HttpCall) -> HttpResponse:
        """Send one request to a reachable luxd or raise ``HubUnavailableError``."""
        ...
