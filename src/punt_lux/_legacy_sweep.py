"""LegacySweep -- the family that cures a service's legacy registrations.

A rename leaves a service's old launchd label or systemd unit registered
under its supervisor even after its plist/unit file is gone -- the exact
failure this family exists to close out
(``docs/architecture/service-lifecycle-migration.md``). :class:`LaunchdLegacySweep`
and :class:`SystemdLegacySweep` satisfy this ``Protocol`` structurally; see
``punt-kit/standards/oo.md`` "Families share by protocol, not base class."
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, final, runtime_checkable

__all__ = ["LegacyServiceOutcome", "LegacySweep", "LegacySweepReport"]


@final
@dataclass(frozen=True, slots=True)
class LegacyServiceOutcome:
    """The sweep's result for one legacy identifier (a launchd label or unit)."""

    identifier: str
    was_present: bool
    deregistered: bool
    config_removed: bool
    verified_clean: bool
    fix_command: str

    def describe(self) -> str:
        """Return an operator-facing repair line, or ``""`` when already clean."""
        if self.verified_clean:
            return ""
        return os.linesep.join(
            (
                f"  {self.identifier}: still registered",
                f"    fix: {self.fix_command}",
            )
        )


@final
@dataclass(frozen=True, slots=True)
class LegacySweepReport:
    """The sweep's result across every legacy identifier for one service."""

    outcomes: tuple[LegacyServiceOutcome, ...]

    @property
    def all_clean(self) -> bool:
        """Return whether every identifier in this report ended up clean."""
        return all(outcome.verified_clean for outcome in self.outcomes)

    def describe(self) -> str:
        """Render every non-clean outcome as an operator-facing repair line."""
        lines = (outcome.describe() for outcome in self.outcomes)
        return os.linesep.join(line for line in lines if line)


@runtime_checkable
class LegacySweep(Protocol):
    """Cure and verify a service's historical launchd/systemd identity."""

    def sweep(self) -> LegacySweepReport:
        """Attempt the cure for every legacy identifier.

        Attempts every identifier to completion -- never short-circuits on
        the first failure -- then raises
        :class:`~punt_lux._service_errors.ServiceMigrationError` once,
        carrying the complete report, if any identifier is still not clean.
        """
        ...

    def is_clean(self) -> bool:
        """Return whether every legacy identifier is already clean, without mutating."""
        ...

    def diagnose(self) -> LegacySweepReport:
        """Return a full report of every identifier's current state, without mutating.

        The non-mutating counterpart to :meth:`sweep` -- ``lux hub doctor``
        (no ``--fix``) calls this so it can render the same
        :meth:`LegacySweepReport.describe` text a failed ``sweep()`` would
        have raised, with zero side effects.
        """
        ...
