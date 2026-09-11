"""What ``HandshakeConnector.connect`` produces: a result, or a failure.

The two outcomes of one operation, in one module -- a success value defined
here, and the failure exception re-exported from its own module
(:mod:`punt_lux.domain.hub.display_not_connected`), where it lives because
two other, unrelated callers (``DisplayLink.connect``,
``HubReplicator``) also raise and catch it independently of any handshake.
Bundling both under the handshake's own vocabulary keeps
``handshake_connector.py`` importing one module for what a connect attempt
can produce, rather than two.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import final

from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.protocol import ReadyMessage

__all__ = ["DisplayNotConnectedError", "HandshakeResult"]


@final
@dataclass(frozen=True, slots=True)
class HandshakeResult:
    """The socket and ``ReadyMessage`` a completed handshake produced."""

    sock: socket.socket
    socket_path: Path
    ready: ReadyMessage
