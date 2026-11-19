"""Detached Python child sessions and their actual parent's lifetime."""

from __future__ import annotations

import asyncio
import os
import signal


class ProcessSession:
    @staticmethod
    def detach() -> None:
        if os.getsid(0) != os.getpid():
            os.setsid()

    @staticmethod
    async def wait_for_parent(parent: int) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        while os.getppid() == parent and not stop.is_set():
            await asyncio.sleep(0.05)
