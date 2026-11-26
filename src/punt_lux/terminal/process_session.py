"""Detached Python child sessions and their actual parent's lifetime."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from punt_lux.kernel.logging_config import record_signal

logger = logging.getLogger(__name__)


class ProcessSession:
    @staticmethod
    def detach() -> None:
        if os.getsid(0) != os.getpid():
            try:
                os.setsid()
            except PermissionError:
                return

    @staticmethod
    async def wait_for_parent(parent: int) -> None:
        """Return when a signal arrives or ``parent`` is no longer the parent.

        Either cause is logged, so the process's exit always names its reason.
        """
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def stopped_by(number: int) -> None:
            record_signal(number)
            stop.set()

        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stopped_by, sig)
        while os.getppid() == parent and not stop.is_set():
            await asyncio.sleep(0.05)
        if not stop.is_set():
            logger.warning("parent pid=%d is gone; stopping", parent)
