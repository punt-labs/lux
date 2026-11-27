"""The transport-observed peer address, independent of an HTTP framework."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["HeaderedConnection", "PeerAddress", "PeerConnection"]


class PeerAddress(Protocol):
    """The host reported by an accepted transport connection."""

    @property
    def host(self) -> str:
        """Return the socket peer's host, never a forwarded header."""
        ...


class PeerConnection(Protocol):
    """A transport connection whose peer may be unreported."""

    @property
    def client(self) -> PeerAddress | None:
        """Return the reported peer or None when the transport has none."""
        ...


class HeaderedConnection(PeerConnection, Protocol):
    """A transport connection that carries request headers and reports its peer."""

    @property
    def headers(self) -> Mapping[str, str]:
        """Return the headers the connection arrived with."""
        ...
