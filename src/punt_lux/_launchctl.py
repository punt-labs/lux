"""Shared ``launchctl`` invocation for ``LaunchdBackend`` and ``LaunchdLegacySweep``."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["launchctl"]


@final
class LaunchctlSubsystem:
    """Run a ``launchctl`` subcommand, logging a warning on non-zero exit."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def gui_domain() -> str:
        """Return this user's launchd GUI domain target, e.g. ``gui/501``."""
        return f"gui/{os.getuid()}"

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
