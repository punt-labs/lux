"""HeaderedPeer -- a connection stand-in: its headers and the peer it came from."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping


@final
class _Peer:
    """The socket peer a transport reports."""

    _host: str
    __slots__ = ("_host",)

    def __new__(cls, host: str) -> Self:
        self = super().__new__(cls)
        self._host = host
        return self

    @property
    def host(self) -> str:
        """The peer's address."""
        return self._host


@final
class HeaderedPeer:
    """A ``HeaderedConnection``; ``host=None`` is an unreported peer."""

    _headers: Mapping[str, str]
    _peer: _Peer | None
    __slots__ = ("_headers", "_peer")

    def __new__(cls, headers: Mapping[str, str], host: str | None = None) -> Self:
        self = super().__new__(cls)
        self._headers = headers
        self._peer = None if host is None else _Peer(host)
        return self

    @property
    def headers(self) -> Mapping[str, str]:
        """The headers the connection arrived with."""
        return self._headers

    @property
    def client(self) -> _Peer | None:
        """The reported peer, or ``None``."""
        return self._peer
