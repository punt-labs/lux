"""SocketListenerCallbacks -- the three domain-reaction callbacks a
``SocketListener`` delegates to.

Bundled as one value object (DES-090 W8) rather than three loose
constructor parameters: pure networking (``SocketListener``) stays
decoupled from the domain reactions (scene ownership, menu cleanup, error
reporting) a caller wires in, and the three callbacks travel together as
the one cohesive "how this listener talks back to its owner" contract.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.protocol.messages import Message

__all__ = ["SocketListenerCallbacks"]


@dataclass(frozen=True, slots=True)
class SocketListenerCallbacks:
    """The callbacks ``SocketListener`` fires for a message, disconnect, or error."""

    on_message: Callable[[socket.socket, Message], None]
    on_client_disconnected: Callable[[int], None]
    on_error: Callable[[str, str, str], None]
