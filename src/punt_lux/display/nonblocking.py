"""Nonblocking -- the one ``noqa: FBT003`` for socket non-blocking mode.

``socket.socket.setblocking`` takes a positional ``bool`` that ruff's
FBT003 (boolean-positional-value-in-call) flags at every call site. One
shared method carries the single justified suppression so every accept
path across the socket layer (``AF_UNIX`` and cross-host TLS alike) calls
a self-documenting name instead of repeating the same ``# noqa``.
"""

from __future__ import annotations

import socket
from typing import Self, final

__all__ = ["Nonblocking"]


@final
class Nonblocking:
    """Namespace for putting a socket into non-blocking mode."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def set(sock: socket.socket) -> None:
        """Put ``sock`` into non-blocking mode."""
        sock.setblocking(False)  # noqa: FBT003
