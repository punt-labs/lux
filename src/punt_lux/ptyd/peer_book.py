"""Authenticated connection roster and bounded socket servicing."""

from __future__ import annotations

import logging
import socket
from typing import Self

from punt_lux.ptyd.credentials import PeerCredentials
from punt_lux.ptyd.dispatch import SessionDispatch
from punt_lux.ptyd.lifetime import DaemonLifetime
from punt_lux.ptyd.peer import Peer

logger = logging.getLogger(__name__)


class PeerBook:
    _peers: dict[socket.socket, Peer]
    _dispatch: SessionDispatch
    _idle: DaemonLifetime

    def __new__(cls, dispatch: SessionDispatch, idle_timeout: float | None) -> Self:
        self = super().__new__(cls)
        self._peers = {}
        self._dispatch = dispatch
        self._idle = DaemonLifetime(idle_timeout)
        return self

    @property
    def readers(self) -> tuple[socket.socket, ...]:
        return tuple(self._peers)

    @property
    def writers(self) -> tuple[socket.socket, ...]:
        return tuple(sock for sock, peer in self._peers.items() if peer.wants_write)

    def service(self, reads: list[socket.socket], writes: list[socket.socket]) -> None:
        for sock in reads:
            peer = self._peers.get(sock)
            if peer is not None:
                self._read(peer)
        for sock in writes:
            peer = self._peers.get(sock)
            if peer is not None and not peer.closed:
                try:
                    peer.flush()
                except (OSError, ConnectionError):
                    self._drop(peer)

    def accept(self, listener: socket.socket) -> None:
        try:
            sock, _address = listener.accept()
        except BlockingIOError:
            return
        try:
            if len(self._peers) >= 8:
                raise PermissionError("viewer connection limit reached")
            PeerCredentials.require_same_user(sock)
            self._peers[sock] = Peer(sock)
        except OSError:
            sock.close()

    def purge(self) -> None:
        for peer in list(self._peers.values()):
            if peer.closed:
                self._drop(peer)

    def expired(self, sessions: int) -> bool:
        if idle := self._idle.expired(len(self._peers), sessions):
            logger.info("Terminal daemon idle with no clients or sessions; stopping")
        return idle

    def close(self) -> None:
        for peer in list(self._peers.values()):
            self._drop(peer)

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
