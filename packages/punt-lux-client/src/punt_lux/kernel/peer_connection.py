"""The transport-observed peer address, independent of an HTTP framework."""

from __future__ import annotations

from typing import Protocol

__all__ = ["PeerAddress", "PeerConnection"]


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
