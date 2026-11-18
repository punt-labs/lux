"""Owned Hub helper keeps the forkpty/native owner single-threaded."""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Self

from punt_lux.ptyd.child import ChildLifetime

logger = logging.getLogger(__name__)


class MenuProcess:
    _child: ChildLifetime | None
    _stopping: bool
    _retry_at: float

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._child = None
        self._stopping = False
        self._retry_at = 0
        return self

    def start(self) -> None:
        self.poll()

    def poll(self) -> None:
        if self._stopping:
            return
        if self._child is not None and not self._child.poll():
            return
        if time.monotonic() >= self._retry_at:
            self._spawn()

    def request_stop(self) -> None:
        self._stopping = True

    def close(self) -> None:
        self.request_stop()
        if self._child is not None:
            self._child.stop()

    def _spawn(self) -> None:
        self._retry_at = time.monotonic() + 5
        argv = [sys.executable, "-m", "punt_lux.ptyd.menu_entry", str(os.getpid())]
        try:
            pid = os.posix_spawn(sys.executable, argv, dict(os.environ), setsid=True)
        except OSError:
            logger.exception("Terminal menu helper could not start; owner stays live")
            return
        self._child = ChildLifetime(pid)
