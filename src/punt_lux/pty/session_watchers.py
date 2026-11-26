"""Peers subscribed to session created/ended events, each with a bounded queue."""

from __future__ import annotations

from collections import deque
from typing import Self

from punt_lux.pty.peer import Peer
from punt_lux.wire.stream.frames import Frame, FrameKind
from punt_lux.wire.stream.session_events import SessionEvent


class SessionWatchers:
    """Fan session events out to watchers without ever blocking the daemon.

    A watcher whose queue overflows is closed rather than skipped: it must
    notice the loss, re-dial and reconcile against the session list.
    """

    _queues: dict[Peer, deque[SessionEvent]]
    _limit: int

    def __new__(cls, limit: int = 64) -> Self:
        if limit < 1:
            raise ValueError("watcher queue limit must be positive")
        self = super().__new__(cls)
        self._queues = {}
        self._limit = limit
        return self

    def __len__(self) -> int:
        return len(self._queues)

    def subscribe(self, peer: Peer) -> None:
        """Turn ``peer`` into a watcher; a connection watches at most once."""
        if peer in self._queues:
            raise ValueError("connection is already watching")
        self._queues[peer] = deque()

    def detach(self, peer: Peer) -> None:
        """Forget ``peer`` after its connection went away."""
        self._queues.pop(peer, None)

    def publish(self, event: SessionEvent) -> None:
        """Queue ``event`` for every watcher, dropping any that overflow."""
        for peer, queue in tuple(self._queues.items()):
            queue.append(event)
            if len(queue) > self._limit:
                self._drop(peer)

    def drain(self) -> None:
        """Hand queued events to watchers whose previous bytes have been sent.

        Waiting for the socket to flush keeps a watch reply ahead of the
        events that follow it, and lets a slow reader's queue fill and overflow.
        """
        for peer, queue in tuple(self._queues.items()):
            if peer.closed:
                self.detach(peer)
            elif queue and not peer.wants_write:
                self._send(peer, queue)

    def _send(self, peer: Peer, queue: deque[SessionEvent]) -> None:
        try:
            while queue:
                peer.queue(Frame(0, FrameKind.DATA, queue[0].encode()))
                queue.popleft()
        except (ConnectionError, BufferError):
            self._drop(peer)

    def _drop(self, peer: Peer) -> None:
        self.detach(peer)
        peer.close()
