"""Start one terminal on the local daemon with a short exchange over its socket."""

from __future__ import annotations

import os
import select
import socket
import time
from pathlib import Path
from typing import Self

from punt_lux.kernel.credentials import PeerCredentials
from punt_lux.pty.peer import Peer
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.control import WIRE_VERSION, ControlCodec, ControlRequest
from punt_lux.wire.stream.frames import Frame, FrameKind
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply

SOCKET_ENVIRONMENT = "LUX_PTY_SOCKET"  # the daemon exports it in PtyServer
TIMEOUT_S = 5.0


class SessionStarter:
    """Ask the daemon at ``path`` for a new login-shell session."""

    _path: Path

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        return self

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def local(cls) -> Self:
        """Dial the socket the daemon exported to its helpers."""
        return cls(Path(os.environ[SOCKET_ENVIRONMENT]))

    def start(self) -> str:
        """Return the id of a new session; blocks for a bounded time.

        Raises:
            OSError: The daemon is unreachable, hung up or did not answer in time.
            RuntimeError: The daemon refused the request.
        """
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT_S)
            sock.connect(str(self._path))
            PeerCredentials.require_same_user(sock)
            peer = Peer(sock)
            self._ask(peer, HelloRequest(1, WIRE_VERSION, snapshot_version()))
            reply = self._ask(peer, NewRequest(2))
        return str(reply.result["session"])

    @staticmethod
    def _ask(peer: Peer, request: ControlRequest) -> SuccessReply:
        peer.queue(Frame(0, FrameKind.DATA, ControlCodec.encode(request)))
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            writing = [peer.socket] if peer.wants_write else []
            select.select([peer.socket], writing, [], 0.1)
            peer.flush()
            try:
                frames = peer.receive()
            except EOFError as error:
                raise ConnectionError("luxd-pty closed the connection") from error
            for frame in frames:
                reply = ReplyCodec.decode(frame.payload)
                if isinstance(reply, FailureReply):
                    raise RuntimeError(reply.error)
                return reply
        raise TimeoutError("luxd-pty did not answer")
