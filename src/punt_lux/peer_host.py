"""PeerHost -- the host a connection was observed arriving from."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from starlette.requests import HTTPConnection

__all__ = ["PeerHost"]


@final
class PeerHost:
    """The socket peer one connection's transport reported.

    Starlette's ``client`` is the address of the accepted TCP socket -- the same
    on a request and on a WebSocket. It is read from there and from nowhere else:
    no forwarding header, no declaration (luxd turns uvicorn's ``proxy_headers``
    off so the socket peer is what the server reports).
    """

    _connection: HTTPConnection
    __slots__ = ("_connection",)

    def __new__(cls, connection: HTTPConnection) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        return self

    @property
    def host(self) -> str | None:
        """The peer's host, or ``None`` if the transport reported no peer."""
        client = self._connection.client
        return None if client is None else client.host
