"""Run a luxd-pty whose launcher table comes from the test that started it."""

from __future__ import annotations

import argparse
import signal
from functools import partial
from pathlib import Path
from types import FrameType
from unittest.mock import patch

from punt_lux.pty.core import SessionCore
from punt_lux.pty.server import PtyServer
from tests.pty.launchers import TestLaunchers


class LauncherDaemon:
    """Foreground entry point mirroring ``python -m punt_lux.pty --no-menu``."""

    @staticmethod
    def main() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--socket", type=Path, required=True)
        # Process creation is the one boundary a test replaces: sessions start
        # the programs the test listed instead of the user's login shell.
        core = partial(SessionCore, TestLaunchers.from_environment())
        with patch("punt_lux.pty.server.SessionCore", core):
            server = PtyServer(parser.parse_args().socket.absolute(), idle_timeout=30)

        def stop(_number: int, _frame: FrameType | None) -> None:
            server.stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.run()


if __name__ == "__main__":
    LauncherDaemon.main()
