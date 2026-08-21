"""Shared ``launchctl`` invocation for ``LaunchdBackend`` and ``LaunchdLegacySweep``."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["gui_domain", "launchctl"]


def gui_domain() -> str:
    """Return this user's launchd GUI domain target, e.g. ``gui/501``."""
    return f"gui/{os.getuid()}"


@final
class LaunchctlSubsystem:
    """Run a ``launchctl`` subcommand, logging a warning on non-zero exit.

    Every launchd verb LaunchdBackend issues (bootout, bootstrap, unload)
    shares this shape: run the command, capture stderr, log a warning on
    failure, and let the caller decide what a non-zero exit means.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def run(self, args: list[str], *, verb: str) -> bool:
        """Run ``args``, log a warning on non-zero exit, and return success."""
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.warning(
                "launchctl %s failed (rc=%d): %s",
                verb,
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0


launchctl: LaunchctlSubsystem = LaunchctlSubsystem()
