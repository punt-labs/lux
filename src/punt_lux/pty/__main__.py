"""Foreground entry point for the terminal-session daemon."""

from __future__ import annotations

import argparse
import signal
from importlib import import_module
from types import FrameType

from punt_lux.pty.entry_runtime import DaemonOptions, TerminalRuntime


class PtyEntryPoint:
    """Run the independent owner; Display disconnect never reaches this lifecycle."""

    @staticmethod
    @TerminalRuntime.run("daemon", "terminal daemon")
    def main() -> None:
        parser = argparse.ArgumentParser(description="Lux local terminal-session owner")
        options = DaemonOptions.parse(parser)
        try:
            module = import_module("punt_lux.pty.application")
            server = module.PtyApplication(options.socket, menu=options.menu)
        except (ModuleNotFoundError, OSError) as error:
            TerminalRuntime.start_failed(parser, error)

        def stop(_number: int, _frame: FrameType | None) -> None:
            server.stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.run()


if __name__ == "__main__":
    PtyEntryPoint.main()
