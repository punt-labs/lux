"""Foreground entry point for the terminal-session daemon."""

from __future__ import annotations

import argparse
import logging
import signal
from importlib import import_module
from pathlib import Path
from types import FrameType


class PtyEntryPoint:
    """Run the independent owner; Display disconnect never reaches this lifecycle."""

    @staticmethod
    def main() -> None:
        parser = argparse.ArgumentParser(description="Lux local terminal-session owner")
        parser.add_argument(
            "--socket",
            type=Path,
            default=Path.home() / ".punt-labs" / "lux" / "pty" / "luxd-pty.sock",
        )
        args = parser.parse_args()
        logging.basicConfig(level=logging.INFO)
        try:
            module = import_module("punt_lux.ptyd.server")
        except ModuleNotFoundError as error:
            parser.exit(
                1, f"luxd-pty: missing {error.name}; install punt-lux[terminal]\n"
            )
        try:
            server = module.PtyServer(args.socket)
        except OSError as error:
            parser.exit(1, f"luxd-pty: {error}\n")

        def stop(_number: int, _frame: FrameType | None) -> None:
            server.stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.run()


if __name__ == "__main__":
    PtyEntryPoint.main()
