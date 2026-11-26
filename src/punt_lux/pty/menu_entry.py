"""Hub helper exits with its daemon parent; never forks or owns a PTY."""

from __future__ import annotations

import asyncio
import sys

from punt_lux.pty.entry_runtime import TerminalRuntime
from punt_lux.pty.menu_listener import TerminalMenu


class MenuEntryPoint:
    @staticmethod
    async def serve(parent: int) -> None:
        menu = asyncio.create_task(TerminalMenu.local().serve())
        owner = asyncio.create_task(TerminalRuntime.wait_for_owner(parent))
        try:
            await asyncio.wait({menu, owner}, return_when=asyncio.FIRST_COMPLETED)
            if menu.done() and not menu.cancelled():
                menu.result()
        finally:
            menu.cancel()
            owner.cancel()
            await asyncio.gather(menu, owner, return_exceptions=True)

    @staticmethod
    @TerminalRuntime.run("worker", "terminal menu helper")
    def main() -> None:
        asyncio.run(MenuEntryPoint.serve(int(sys.argv[1])))


if __name__ == "__main__":
    MenuEntryPoint.main()
