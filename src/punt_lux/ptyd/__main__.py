"""Foreground entry point for the terminal-session daemon."""

from __future__ import annotations

import argparse
import logging
import os
import signal
from importlib import import_module
from pathlib import Path
from types import FrameType


class PtyEntryPoint:
    """Run the independent owner; Display disconnect never reaches this lifecycle."""

    @staticmethod
    def main() -> None:
        parser = argparse.ArgumentParser(description="Lux local terminal-session owner")
        default = Path.home() / ".punt-labs" / "lux" / "pty" / "luxd-pty.sock"
        parser.add_argument("--socket", type=Path, default=default)
        no_menu = os.environ.get("LUX_PTY_NO_MENU") == "1"
        parser.add_argument("--no-menu", action="store_true", default=no_menu)
        args = parser.parse_args()
        logging.basicConfig(level=logging.INFO)
        try:
            module = import_module("punt_lux.ptyd.application")
        except ModuleNotFoundError as error:
            parser.exit(
                1, f"luxd-pty: missing {error.name}; install punt-lux[terminal]\n"
            )
        try:
            server = module.PtyApplication(args.socket, menu=not args.no_menu)
        except OSError as error:
            parser.exit(1, f"luxd-pty: {error}\n")

        def stop(_number: int, _frame: FrameType | None) -> None:
            server.stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.run()


if __name__ == "__main__":
    PtyEntryPoint.main()
