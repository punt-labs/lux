"""CrossHostPump -- what the render loop needs from the cross-host listener.

The render loop drives the opt-in cross-host TLS listener through this narrow
structural port, not the concrete
:class:`~punt_lux.display.cross_host_listener.CrossHostListener`: it only ever
accepts pending peers, collects the ones whose handshake completed, and shuts
the socket down. Depending on the Protocol rather than the ``@final`` class
keeps the render loop decoupled from the TLS transport and lets a windowless
test drive the exact per-frame cadence with a stand-in (families share by
Protocol, not a base class).
"""

from __future__ import annotations

import socket
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

__all__ = ["CrossHostPump"]


@runtime_checkable
class CrossHostPump(Protocol):
    """The accept/collect/shutdown surface the render loop pumps each frame."""

    def accept_pending(self) -> None:
        """Accept any newly-connected TLS peers into the pending-handshake set."""
        ...

    def pump_ready(self) -> Sequence[socket.socket]:
        """Drive each pending handshake one step; return the newly-verified sockets."""
        ...

    def shutdown(self) -> None:
        """Close the listening socket and every pending (unverified) connection."""
        ...
