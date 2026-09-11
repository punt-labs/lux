"""HandshakeConnector -- the ``AF_UNIX`` dialer and the shared handshake.

Extracted from :class:`DisplayLink.connect` (PY-OO-5, PY-IC-6): the
socket-open, send-timeout, and ``ReadyMessage``/``ConnectMessage`` handshake
sequence touches none of ``DisplayLink``'s listener-thread or reply-queue
state -- it needs only an endpoint, a spawn policy, a timeout budget, and this
connection's own declared identity (``kind`` plus :class:`HubId`) to build the
``ConnectMessage`` it sends. It satisfies the :class:`DisplayDialer` protocol
for the local leg, and its :meth:`complete_handshake` -- the transport-agnostic
tail (recv ``ReadyMessage``, send ``ConnectMessage``) -- is what the cross-host
:class:`~punt_lux.domain.hub.cross_host_connector.CrossHostConnector` reuses on
a socket it opened over TLS, so the connect sequence is written once.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Literal, Self, final

from punt_lux.domain.hub.handshake_outcome import (
    DisplayNotConnectedError,
    HandshakeResult,
)
from punt_lux.domain.hub_id import HubId
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import ConnectMessage, ReadyMessage, recv_message, send_message
from punt_lux.send_timeout import set_send_timeout

__all__ = ["HandshakeConnector", "HandshakeResult"]

logger = logging.getLogger(__name__)


@final
class HandshakeConnector:
    """Dials the display over ``AF_UNIX`` and performs the connect handshake.

    Owns this connection's declared identity -- the display-facing ``name``,
    its ``kind``, and its :class:`HubId` -- all fixed for the connection's
    lifetime, plus the local endpoint (``socket_path``) and whether to spawn
    the display when it is not already running.
    """

    _name: str | None
    _kind: Literal["hub", "test"]
    _hub_id: HubId
    _socket_path: Path | None
    _auto_spawn: bool

    def __new__(
        cls,
        *,
        name: str | None,
        kind: Literal["hub", "test"],
        socket_path: str | Path | None = None,
        auto_spawn: bool = True,
    ) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._kind = kind
        self._hub_id = HubId.current() if kind == "hub" else HubId.stub()
        self._socket_path = Path(socket_path) if socket_path else None
        self._auto_spawn = auto_spawn
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        """Open the display socket and perform the Ready/Connect handshake.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start, the handshake times out or
            mismatches, or the declared-identity ``ConnectMessage`` fails to
            send. The opened socket is closed on every failure path -- no
            caller ever sees a half-open connection.
        """
        dp = DisplayPaths(self._socket_path)
        path = dp.ensure(connect_timeout) if self._auto_spawn else dp.socket_path
        self._socket_path = path  # cache the resolved default for a later re-dial

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            sock.close()
            msg = f"Cannot connect to display at {path}: {exc}"
            raise DisplayNotConnectedError(msg) from exc

        set_send_timeout(sock)
        return self.complete_handshake(sock, str(path), connect_timeout)

    def complete_handshake(
        self, sock: socket.socket, endpoint: str, connect_timeout: float
    ) -> HandshakeResult:
        """Run the transport-agnostic tail on an already-open ``sock``.

        Receives and validates the ``ReadyMessage``, then sends this
        connection's ``ConnectMessage``. Shared by the local dial above and
        by ``CrossHostConnector`` on a TLS socket it has already handshaked,
        so the wire sequence exists in exactly one place. ``sock`` is closed
        on every failure path.
        """
        ready = self._recv_ready(sock, endpoint, connect_timeout)
        self._send_identity(sock)
        logger.info("Connected to display at %s (protocol %s)", endpoint, ready.version)
        return HandshakeResult(sock=sock, endpoint=endpoint, ready=ready)

    def _recv_ready(
        self, sock: socket.socket, endpoint: str, connect_timeout: float
    ) -> ReadyMessage:
        """Receive and validate the ``ReadyMessage``, closing ``sock`` on failure."""
        try:
            ready = recv_message(sock, timeout=connect_timeout)
        except Exception:
            sock.close()
            raise
        if ready is None:
            sock.close()
            msg = f"Handshake timed out after {connect_timeout}s at {endpoint}"
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
