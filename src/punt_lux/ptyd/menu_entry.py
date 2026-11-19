"""Hub helper exits with its daemon parent; never forks or owns a PTY."""

from __future__ import annotations

import asyncio
import sys

from punt_lux.ptyd.entry_runtime import TerminalRuntime
from punt_lux.ptyd.menu_listener import TerminalMenu


class MenuEntryPoint:
    @staticmethod
    async def serve(parent: int) -> None:
        task = asyncio.create_task(TerminalMenu().serve())
        try:
            await TerminalRuntime.wait_for_owner(parent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def main() -> None:
        TerminalRuntime.start("worker", "terminal menu helper")
        asyncio.run(MenuEntryPoint.serve(int(sys.argv[1])))


if __name__ == "__main__":
    MenuEntryPoint.main()
