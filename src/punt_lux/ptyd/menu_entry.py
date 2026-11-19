"""Hub helper exits with its daemon parent; never forks or owns a PTY."""

from __future__ import annotations

import asyncio
import sys

from punt_lux.ptyd.menu_listener import TerminalMenu
from punt_lux.terminal.process_session import ProcessSession


class MenuEntryPoint:
    @staticmethod
    async def serve(parent: int) -> None:
        task = asyncio.create_task(TerminalMenu().serve())
        try:
            await ProcessSession.wait_for_parent(parent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def main() -> None:
        ProcessSession.detach()
        asyncio.run(MenuEntryPoint.serve(int(sys.argv[1])))


if __name__ == "__main__":
    MenuEntryPoint.main()
