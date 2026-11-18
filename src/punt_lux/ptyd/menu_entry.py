"""Hub helper exits with its daemon parent; never forks or owns a PTY."""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from punt_lux.ptyd.menu_clients import TerminalClients
from punt_lux.ptyd.menu_listener import TerminalMenu


class MenuEntryPoint:
    @staticmethod
    async def serve(parent: int) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        task = asyncio.create_task(TerminalMenu(TerminalClients()).serve())
        try:
            # getppid changes on parent death; no PID-liveness/reuse heuristic.
            while os.getppid() == parent and not stop.is_set():
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def main() -> None:
        asyncio.run(MenuEntryPoint.serve(int(sys.argv[1])))


if __name__ == "__main__":
    MenuEntryPoint.main()
