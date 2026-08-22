"""Shared ``launchctl`` invocation for ``LaunchdBackend`` and ``LaunchdLegacySweep``."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["launchctl"]

# launchd's rc for "no such service in this domain" — the answer to an
# existence probe, not a failure. Both ``launchctl print`` (used by the
# legacy sweep and the self-upgrade probe to ask "is this label loaded?")
# and ``launchctl bootout`` (idempotent deregistration) exit with this
# code when the label is absent, and neither caller wants that reported
# as a scary warning on a clean machine.
_LAUNCHD_NOT_FOUND_RC = 113
_EXISTENCE_PROBE_QUIET_EXITS = frozenset({_LAUNCHD_NOT_FOUND_RC})


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

    def run(
        self,
        args: list[str],
        *,
        verb: str,
        quiet_exits: frozenset[int] = frozenset(),
    ) -> bool:
        """Run ``args``, log a warning on non-zero exit, and return success.

        ``quiet_exits`` names exit codes that carry information for the
        caller but no failure signal for the user — the caller still sees
        ``False`` and reacts accordingly, but no warning is logged.
        """
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0 and result.returncode not in quiet_exits:
            logger.warning(
                "launchctl %s failed (rc=%d): %s",
                verb,
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0

    def probe(self, args: list[str], *, verb: str) -> bool:
        """Run an existence probe: ``False`` for "not registered" is expected.

        A probe asks "does this label exist in this domain?" and launchd
        answers with rc=113 for "no" — that is the probe's return value,
        not a failure to report.
        """
        return self.run(args, verb=verb, quiet_exits=_EXISTENCE_PROBE_QUIET_EXITS)


launchctl: LaunchctlSubsystem = LaunchctlSubsystem()
