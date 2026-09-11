"""set_nonblocking -- the one ``noqa: FBT003`` for socket non-blocking mode.

``socket.socket.setblocking`` takes a positional ``bool`` that ruff's
FBT003 (boolean-positional-value-in-call) flags at every call site. One
shared wrapper carries the single justified suppression so every accept
path across the socket layer (``AF_UNIX`` and cross-host TLS alike) calls
a self-documenting name instead of repeating the same ``# noqa``.
"""

from __future__ import annotations

import socket

__all__ = ["set_nonblocking"]


def set_nonblocking(sock: socket.socket) -> None:
    """Put ``sock`` into non-blocking mode."""
    sock.setblocking(False)  # noqa: FBT003
