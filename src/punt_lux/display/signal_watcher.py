"""Notice SIGTERM on a thread of its own and end the process if the loop cannot."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from typing import TYPE_CHECKING, ClassVar, Self, final

from punt_lux.kernel.logging_config import record_signal

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["SignalWatcher"]

logger = logging.getLogger(__name__)


@final
class SignalWatcher:
    """Act on SIGTERM even while the main thread is stuck in native code.

    A Python signal handler runs only on the main thread, between bytecodes. While
    that thread sits in the ImGui loop, which macOS stops waking once the window is
    not visible, the handler never runs and a stop request goes unanswered until a
    supervisor sends SIGKILL, with nothing logged. The interpreter's own signal
    trip writes the signal number to a wakeup descriptor from whichever thread
    receives it, so this thread reads that descriptor, logs the signal, asks the
    loop to stop, and ends the process after a grace if the loop has not. The forced
    exit status is 128 plus SIGTERM, a failure to a supervisor that restarts on failure.

    Construct on the main thread: ``signal.set_wakeup_fd`` allows no other.
    """

    GRACE_S: ClassVar[float] = 2.0

    __slots__ = ("_grace_s", "_reader", "_request_exit", "_thread", "_writer")

    _grace_s: float
    _reader: socket.socket
    _request_exit: Callable[[], None]
    _thread: threading.Thread
    _writer: socket.socket

    def __new__(
        cls, request_exit: Callable[[], None], grace_s: float = GRACE_S
    ) -> Self:
        self = super().__new__(cls)
        self._request_exit, self._grace_s = request_exit, grace_s
        self._reader, self._writer = socket.socketpair()
        self._writer.settimeout(0.0)
        signal.set_wakeup_fd(self._writer.fileno(), warn_on_full_buffer=False)
        self._thread = threading.Thread(
            target=self._watch, name="signal-watcher", daemon=True
        )
        self._thread.start()
        return self

    def _watch(self) -> None:
        while data := self._reader.recv(1):
            if data[0] == signal.SIGTERM:
                self._stop()

    def _stop(self) -> None:
        record_signal(signal.SIGTERM)
        self._request_exit()
        time.sleep(self._grace_s)
        logger.error(
            "Display did not exit %.1f s after SIGTERM; ending the process",
            self._grace_s,
        )
        os._exit(128 + signal.SIGTERM)
