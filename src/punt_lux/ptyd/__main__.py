"""Foreground entry point for the terminal-session daemon."""

from __future__ import annotations

import argparse
import signal
from importlib import import_module
from types import FrameType

from punt_lux.ptyd.entry_runtime import (
    DaemonOptions,
    start_terminal_process,
    terminal_start_failed,
)


class PtyEntryPoint:
    """Run the independent owner; Display disconnect never reaches this lifecycle."""

    @staticmethod
    def main() -> None:
        start_terminal_process("daemon", "terminal daemon")
        parser = argparse.ArgumentParser(description="Lux local terminal-session owner")
        options = DaemonOptions.parse(parser)
        try:
            module = import_module("punt_lux.ptyd.application")
            server = module.PtyApplication(options.socket, menu=options.menu)
        except (ModuleNotFoundError, OSError) as error:
            terminal_start_failed(parser, error)

        def stop(_number: int, _frame: FrameType | None) -> None:
            server.stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.run()


if __name__ == "__main__":
    PtyEntryPoint.main()
