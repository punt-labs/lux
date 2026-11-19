"""Hub helper exits with its daemon parent; never forks or owns a PTY."""

from __future__ import annotations

import asyncio
import sys

from punt_lux.ptyd.entry_runtime import start_terminal_process, wait_for_terminal_owner
from punt_lux.ptyd.menu_listener import TerminalMenu


class MenuEntryPoint:
    @staticmethod
    async def serve(parent: int) -> None:
        task = asyncio.create_task(TerminalMenu().serve())
        try:
            await wait_for_terminal_owner(parent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def main() -> None:
        start_terminal_process("worker", "terminal menu helper")
        asyncio.run(MenuEntryPoint.serve(int(sys.argv[1])))


if __name__ == "__main__":
    MenuEntryPoint.main()
