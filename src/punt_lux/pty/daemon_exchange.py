"""One request and one reply over the local terminal daemon's socket."""

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
from punt_lux.wire.stream.frames import Frame, FrameError, FrameKind
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply

SOCKET_ENVIRONMENT = "LUX_PTY_SOCKET"  # the daemon exports it in PtyServer
TIMEOUT_S = 5.0


class SessionRefusedError(RuntimeError):
    """The daemon refused a request, or answered one in a way that cannot be read."""


class RetryableRefusalError(SessionRefusedError):
    """The daemon refused, and said the same request may succeed later."""


class DaemonExchange:
    """Send one request to the daemon at ``path`` and decode its one reply."""

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

    def ask(self, request: ControlRequest) -> SuccessReply:
        """Return the daemon's answer to ``request``; blocks for a bounded time.

        Raises:
            OSError: The daemon is unreachable, hung up or did not answer in time.
            SessionRefusedError: The daemon refused the request or answered nonsense.
        """
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT_S)
            sock.connect(str(self._path))
            PeerCredentials.require_same_user(sock)
            peer = Peer(sock)
            self._converse(peer, HelloRequest(1, WIRE_VERSION, snapshot_version()))
            return self._converse(peer, request)

    @staticmethod
    def _converse(peer: Peer, request: ControlRequest) -> SuccessReply:
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
            except FrameError as error:
                raise RetryableRefusalError(
                    "luxd-pty sent an unreadable frame"
                ) from error
            for frame in frames:
                try:
                    reply = ReplyCodec.decode(frame.payload)
                except ValueError as error:
                    raise RetryableRefusalError(
                        "luxd-pty sent an unreadable reply"
                    ) from error
                if isinstance(reply, FailureReply):
                    refusal = (
                        RetryableRefusalError
                        if reply.retryable
                        else SessionRefusedError
                    )
                    raise refusal(reply.error)
                return reply
        raise TimeoutError("luxd-pty did not answer")
