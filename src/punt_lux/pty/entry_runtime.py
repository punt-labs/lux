"""Bootstrap diagnostics and process ownership for terminal entry points."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, NoReturn, Self, final

from punt_lux.kernel.home_paths import LuxHome
from punt_lux.kernel.logging_config import failure_details, process_diagnostics
from punt_lux.terminal.process_session import ProcessSession

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from collections.abc import Generator

logger = logging.getLogger(__name__)
_INSTALL_HINT = "; install punt-lux[terminal]"


class DaemonOptions(NamedTuple):
    """The terminal daemon's socket location and menu integration switch."""

    socket: Path
    menu: bool

    @classmethod
    def parse(cls, parser: ArgumentParser) -> Self:
        """Parse the terminal daemon's command-line options."""
        parser.add_argument("--socket", type=Path)
        no_menu = os.environ.get("LUX_PTY_NO_MENU") == "1"
        parser.add_argument("--no-menu", action="store_true", default=no_menu)
        args = parser.parse_args()
        return cls(LuxHome.terminal_socket(args.socket), not args.no_menu)


@final
class TerminalRuntime:
    """Run the shared terminal process bootstrap and owner lifecycle."""

    @staticmethod
    @contextmanager
    def run(role: str, name: str) -> Generator[None]:
        """Configure diagnostics before detaching and through process shutdown."""
        with process_diagnostics(role, name):
            logger.info("Starting %s", name)
            yield ProcessSession.detach()
            logger.info("Stopped %s", name)

    @staticmethod
    def start_failed(parser: ArgumentParser, error: Exception) -> NoReturn:
        """Report a daemon startup failure to the operator and durable sink."""
        hint = _INSTALL_HINT if isinstance(error, ModuleNotFoundError) else ""
        logger.error("Terminal daemon could not start: %s", failure_details(error))
        parser.exit(1, f"luxd-pty: {error}{hint}\n")

    @staticmethod
    async def wait_for_owner(parent: int) -> None:
        """Wait for owner exit or worker shutdown."""
        await ProcessSession.wait_for_parent(parent)
        logger.info("Terminal menu helper stopping (owner pid=%d)", parent)
