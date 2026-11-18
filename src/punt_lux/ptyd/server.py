"""Foreground Unix service; viewer disconnects do not own process lifetime."""

from __future__ import annotations

import logging
import select
import socket
from pathlib import Path
from typing import Self

from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.credentials import PeerCredentials
from punt_lux.ptyd.dispatch import SessionDispatch
from punt_lux.ptyd.endpoint import LocalEndpoint
from punt_lux.ptyd.peer import Peer

logger = logging.getLogger(__name__)


class PtyServer:
    """Single-threaded socket/core coordinator with bounded peer count."""

    _endpoint: LocalEndpoint
    _core: SessionCore
    _dispatch: SessionDispatch
    _peers: dict[socket.socket, Peer]
    _stopping: bool

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._endpoint = LocalEndpoint(path)
        try:
            self._core = SessionCore()
            self._dispatch = SessionDispatch(self._core)
        except BaseException:
            self._endpoint.close()
            raise
        self._peers = {}
        self._stopping = False
        return self

    def stop(self) -> None:
        """Signal handlers set a flag; cleanup executes on the main loop."""
        self._stopping = True

    def run(self) -> None:
        try:
            while not self._stopping:
                self.tick()
        finally:
            self.close()

    def tick(self, timeout: float = 0.005) -> None:
        self._purge_closed()
        listener = self._endpoint.listener
        reads = [listener, *self._peers]
        writes = [sock for sock, peer in self._peers.items() if peer.wants_write]
        ready, writable, _ = select.select(reads, writes, [], timeout)
        for sock in ready:
            if sock is listener:
                self._accept()
            elif sock in self._peers:
                self._read(self._peers[sock])
        for sock in writable:
            peer = self._peers.get(sock)
            if peer is not None and not peer.closed:
                try:
                    peer.flush()
                except (OSError, ConnectionError):
                    self._drop(peer)
        self._dispatch.pump()

    def _accept(self) -> None:
        try:
            sock, _address = self._endpoint.listener.accept()
        except BlockingIOError:
            return
        try:
            if len(self._peers) >= 8:
                raise PermissionError("viewer connection limit reached")
            PeerCredentials.require_same_user(sock)
            self._peers[sock] = Peer(sock)
        except (OSError, PermissionError):
            sock.close()

    def _read(self, peer: Peer) -> None:
        try:
            for frame in peer.receive():
                self._dispatch.receive(peer, frame)
        except (EOFError, ValueError, OSError, RuntimeError, BufferError) as error:
            logger.debug("terminal viewer disconnected: %s", error)
            self._drop(peer)

    def _drop(self, peer: Peer) -> None:
        self._dispatch.detach(peer)
        self._peers.pop(peer.socket, None)
        peer.close()

    def _purge_closed(self) -> None:
        for peer in list(self._peers.values()):
            if peer.closed:
                self._drop(peer)

    def close(self) -> None:
        for peer in list(self._peers.values()):
            self._drop(peer)
        self._endpoint.close()
        self._core.close()
