"""SocketLine -- the lock a dial's socket is taken under, and the bytes that move on it.

A dial's socket is read by one reader at a time and written by one writer at a time,
and a TLS socket forbids a read and a write at once, so both take this lock. Whether
a lock held by a writer is a wedge or merely a slow peer is judged by the one clock of
the bytes that move on the socket (:class:`~punt_lux.progress_clock.ProgressClock`):
a wait for the lock, and the bounded write itself, are cut only after ``D`` with no
byte moving, and so is the keepalive's verdict. A peer that stops reading cannot wedge
a writer for ever: every write is one user-space bounded send
(:class:`~punt_lux.bounded_send.BoundedSend`) on a socket made non-blocking for it.
``SO_SNDTIMEO`` bounds only the handshake's blocking send, which the dialers set
before the dial is handed over.
"""

from __future__ import annotations

import select
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, final

from punt_lux.bounded_send import BoundedSend
from punt_lux.domain.hub.lock_discipline import LockDiscipline
from punt_lux.progress_clock import ProgressClock
from punt_lux.send_timeout import SCENE_WRITE_DEADLINE_SECONDS
from punt_lux.write_progress import WriteProgress

if TYPE_CHECKING:
    import socket
    from collections.abc import Generator

__all__ = ["SocketLine"]


@final
class SocketLine:
    """One socket's lock, and the clock of the bytes that move on it."""

    _lock: threading.Lock
    _clock: ProgressClock  # any byte either way: what a wait measures silence by
    _heard: ProgressClock  # incoming bytes only: the keepalive's evidence of life
    _writing: bool  # a write holds the line now
    __slots__ = ("_clock", "_heard", "_lock", "_writing")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._clock = ProgressClock()
        self._heard = ProgressClock()
        self._writing = False
        return self

    @staticmethod
    def readable(sock: socket.socket, timeout: float) -> bool:
        """Wait up to ``timeout`` for ``sock`` to be readable; whether it is.

        Fails first if the caller holds a store lock: a wait made under it breaks the
        rule on a quiet socket as on a busy one.
        """
        LockDiscipline.forbid_store("the dial socket lock")
        readable, _, _ = select.select([sock], [], [], timeout)
        return bool(readable)

    @contextmanager
    def reading(self) -> Generator[None]:
        """Hold the lock for a read, waiting as long as it takes."""
        LockDiscipline.forbid_store("the dial socket lock")
        with self._lock:
            yield

    @contextmanager
    def draining(self, timeout: float) -> Generator[bool]:
        """Hold the lock if it is free within ``timeout`` seconds; say whether it is."""
        LockDiscipline.forbid_store("the dial socket lock")
        free = self._lock.acquire(timeout=timeout)
        try:
            yield free
        finally:
            if free:
                self._lock.release()

    @contextmanager
    def writing(self) -> Generator[bool]:
        """Hold the lock for a write; ``False`` if no byte moves for ``D`` meanwhile.

        The wait is re-armed by progress: a lock held by a writer that keeps moving
        bytes is waited for, since that peer is alive, and only silence ends the wait.
        The silence is measured from the later of the last byte and the moment this
        wait began, so a line that was idle before is not refused at once; taking the
        lock is no progress.
        """
        LockDiscipline.forbid_store("the dial socket lock")
        free = self._acquire_unless_silent()
        self._writing = free
        try:
            yield free
        finally:
            if free:
                self._writing = False
                self._lock.release()

    def moved(self) -> None:
        """Note that application data came in: the display is moving."""
        self._clock.moved()
        self._heard.moved()

    def is_progressing(self) -> bool:
        """Whether the keepalive has no verdict to give: the display spoke within ``D``,
        or a write holds the line and is still moving bytes.

        A write that completed proves only that the kernel took its bytes, and the
        lock being taken proves nothing. A write still progressing is the write's own
        no-progress deadline to judge, so a slow but healthy display is not dropped
        under it; a stalled one ends the dial within ``D`` all the same.
        """
        window = SCENE_WRITE_DEADLINE_SECONDS
        return self._heard.progressed_within(window) or (
            self._writing and self._clock.progressed_within(window)
        )

    def send(self, sock: socket.socket, wire: bytes) -> None:
        """Write all of ``wire``, unless no byte moves for ``D``; the lock is held.

        Its bytes keep the write's own deadline alive, and make a wait for the line
        wait on; they do not count as the display speaking.
        """
        BoundedSend().send_while_progressing(
            sock, wire, WriteProgress(self._clock), SCENE_WRITE_DEADLINE_SECONDS
        )

    def _acquire_unless_silent(self) -> bool:
        window = SCENE_WRITE_DEADLINE_SECONDS
        began = time.monotonic()
        while True:
            due = max(self._clock.expires_at(window), began + window)
            if self._lock.acquire(timeout=max(due - time.monotonic(), 0.0)):
                return True
            if time.monotonic() >= max(self._clock.expires_at(window), began + window):
                return False
