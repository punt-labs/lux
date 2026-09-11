"""HandshakeConnector -- opens the display socket and runs the handshake.

Extracted from :class:`DisplayLink.connect` (PY-OO-5, PY-IC-6): the
socket-open, send-timeout, and ``ReadyMessage``/``ConnectMessage`` handshake
sequence touches none of ``DisplayLink``'s listener-thread or reply-queue
state -- it only needs a socket path, a spawn policy, a timeout budget, and
this connection's own declared identity (``kind`` plus :class:`HubId`) to
build the ``ConnectMessage`` it sends. That is a self-contained collaborator
``DisplayLink`` delegates to, not a method that happens to live on the
transport it hands the finished socket to.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self, final

from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.hub_id import HubId
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    ConnectMessage,
    ReadyMessage,
    recv_message,
    send_message,
)
from punt_lux.send_timeout import set_send_timeout

__all__ = ["HandshakeConnector", "HandshakeResult"]

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True, slots=True)
class HandshakeResult:
    """The socket and ``ReadyMessage`` a completed handshake produced."""

    sock: socket.socket
    socket_path: Path
    ready: ReadyMessage


@final
class HandshakeConnector:
    """Opens the display socket and performs the connect handshake.

    Owns this connection's declared identity -- the display-facing ``name``,
    its ``kind``, and its :class:`HubId` -- all fixed for the connection's
    lifetime, so it can build the ``ConnectMessage`` itself once the
    ``ReadyMessage`` handshake completes.
    """

    _name: str | None
    _kind: Literal["hub", "test"]
    _hub_id: HubId

    def __new__(cls, *, name: str | None, kind: Literal["hub", "test"]) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._kind = kind
        self._hub_id = HubId.current() if kind == "hub" else HubId.stub()
        return self

    def connect(
        self,
        socket_path: Path | None,
        *,
        auto_spawn: bool,
        connect_timeout: float,
    ) -> HandshakeResult:
        """Open the display socket and perform the Ready/Connect handshake.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start, the handshake times out or
            mismatches, or the declared-identity ``ConnectMessage`` fails to
            send. The opened socket is closed on every failure path -- no
            caller ever sees a half-open connection.
        """
        dp = DisplayPaths(socket_path)
        path = dp.socket_path
        if auto_spawn:
            path = dp.ensure(timeout=connect_timeout)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            sock.close()
            msg = f"Cannot connect to display at {path}: {exc}"
            raise DisplayNotConnectedError(msg) from exc

        set_send_timeout(sock)
        ready = self._recv_ready(sock, path, connect_timeout)
        self._send_identity(sock)
        logger.info("Connected to display (protocol %s)", ready.version)
        return HandshakeResult(sock=sock, socket_path=path, ready=ready)

    def _recv_ready(
        self, sock: socket.socket, path: Path, connect_timeout: float
    ) -> ReadyMessage:
        """Receive and validate the ``ReadyMessage``, closing ``sock`` on failure."""
        try:
            ready = recv_message(sock, timeout=connect_timeout)
        except Exception:
            sock.close()
            raise
        if ready is None:
            sock.close()
            msg = f"Handshake timed out after {connect_timeout}s at {path}"
            raise DisplayNotConnectedError(msg)
        if not isinstance(ready, ReadyMessage):
            sock.close()
            # A protocol mismatch (e.g. version skew), not a disconnect: still
            # raises DisplayNotConnectedError so the replicator holds and retries,
            # but a persistent mismatch must stay visible, not vanish into that
            # path's ordinary quiet-disconnected retry cadence.
            logger.warning("Handshake mismatch: expected ReadyMessage, got %s", ready)
            msg = f"Expected ReadyMessage, got {type(ready).__name__}"
            raise DisplayNotConnectedError(msg)
        return ready

    def _send_identity(self, sock: socket.socket) -> None:
        """Send this connection's declared identity, if it has a name."""
        if not self._name:
            return
        try:
            send_message(sock, self._connect_message(self._name))
        except OSError as exc:
            sock.close()
            err = f"ConnectMessage failed after handshake: {exc}"
            raise DisplayNotConnectedError(err) from exc

    def _connect_message(self, name: str) -> ConnectMessage:
        """Build this connection's declared identity, HubId included."""
        return ConnectMessage(
            name=name, kind=self._kind, hub_id=self._hub_id.wire_token
        )
