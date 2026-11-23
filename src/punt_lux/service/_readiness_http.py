"""One absolute I/O deadline, including a socket's complete response body."""

from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Generator


class ProbeDeadline:
    """Socket timeouts and the watchdog spend the same remaining budget."""

    _deadline: float

    def __new__(cls, seconds: float) -> Self:
        self = super().__new__(cls)
        self._deadline = time.monotonic() + seconds
        return self

    def remaining(self) -> float:
        """Require a positive budget before starting another operation."""
        if (remaining := self._deadline - time.monotonic()) <= 0:
            raise TimeoutError("Hub Display probe deadline elapsed")
        return remaining

    @contextmanager
    def watch(self, sock: socket.socket | None) -> Generator[None]:
        """Interrupt a response read without racing the response's cleanup."""
        if sock is None:
            raise ConnectionError("Hub connection has no socket")
        sock.settimeout(self.remaining())
        watchdog = threading.Timer(self.remaining(), self._expire, args=(sock,))
        watchdog.daemon = True
        watchdog.start()
        try:
            yield
        finally:
            watchdog.cancel()
            watchdog.join()

    @staticmethod
    def _expire(sock: socket.socket) -> None:
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
