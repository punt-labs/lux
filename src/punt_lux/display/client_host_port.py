"""ClientHost -- what the display's client readers and senders need of their owner."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import socket

__all__ = ["ClientHost"]


@runtime_checkable
class ClientHost(Protocol):
    """The listener that owns the client sockets, as its reader and sender see it."""

    def remove_client(self, sock: socket.socket) -> None:
        """Drop a dead, severed or malformed client and clean up its per-fd state."""
        ...

    def is_client(self, sock: socket.socket) -> bool:
        """Return whether ``sock`` is still a live registered client."""
        ...
