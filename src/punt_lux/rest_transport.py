"""The HTTP transport contract the CLI's REST client speaks over.

One round-trip, one reply value, one failure. Isolating the contract from the
client lets a test substitute a transport that routes into a ``TestClient``
while the shipped client uses the urllib transport, and keeps the client itself
free of any wire-level concern beyond "send this and read the reply".
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

__all__ = ["HttpResponse", "HttpTransport", "HubUnavailableError"]


class HubUnavailableError(Exception):
    """luxd could not be reached: no port file, a refused connection, or a stall.

    Carries a single actionable sentence for the CLI to print; the command
    catches it at its entry point and exits non-zero without a traceback.
    """


class HttpResponse(BaseModel):
    """One HTTP reply from a reachable luxd: the status and the raw body."""

    model_config = ConfigDict(frozen=True)

    status: int
    body: bytes


class HttpTransport(Protocol):
    """The one HTTP round-trip the client needs, so tests can substitute one.

    The transport owns the endpoint (luxd's loopback host and port); the client
    passes only a method, a path, and an optional body.
    """

    def request(self, method: str, path: str, body: bytes | None) -> HttpResponse:
        """Send one request to a reachable luxd or raise ``HubUnavailableError``."""
        ...
