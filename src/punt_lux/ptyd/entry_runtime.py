"""Bootstrap diagnostics and process ownership for terminal entry points."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, NoReturn, final

from punt_lux.logging_config import configure_logging, failure_details
from punt_lux.terminal.process_session import ProcessSession

if TYPE_CHECKING:
    from argparse import ArgumentParser

logger = logging.getLogger(__name__)


class DaemonOptions(NamedTuple):
    """The terminal daemon's socket location and menu integration switch."""

    socket: Path
    menu: bool

    @staticmethod
    def parse(parser: ArgumentParser) -> DaemonOptions:
        """Parse the terminal daemon's command-line options."""
        default = Path.home() / ".punt-labs" / "lux" / "pty" / "luxd-pty.sock"
        parser.add_argument("--socket", type=Path, default=default)
        no_menu = os.environ.get("LUX_PTY_NO_MENU") == "1"
        parser.add_argument("--no-menu", action="store_true", default=no_menu)
        args = parser.parse_args()
        return DaemonOptions(args.socket, not args.no_menu)


@final
class TerminalRuntime:
    """Run the shared terminal process bootstrap and owner lifecycle."""

    @staticmethod
    def start(role: str, name: str) -> None:
        """Configure diagnostics before detaching a terminal process."""
        configure_logging("lux", role)
        logger.info("Starting %s", name)
        ProcessSession.detach()

    @staticmethod
    def start_failed(parser: ArgumentParser, error: Exception) -> NoReturn:
        """Report a daemon startup failure to the operator and durable sink."""
        hint = (
            "; install punt-lux[terminal]"
            if isinstance(error, ModuleNotFoundError)
            else ""
        )
        logger.error("Terminal daemon could not start: %s", failure_details(error))
        parser.exit(1, f"luxd-pty: {error}{hint}\n")

    @staticmethod
    async def wait_for_owner(parent: int) -> None:
        """Wait for owner exit or worker shutdown."""
        await ProcessSession.wait_for_parent(parent)
        logger.info("Terminal menu helper stopping (owner pid=%d)", parent)
