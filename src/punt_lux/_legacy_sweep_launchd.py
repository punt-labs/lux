"""LaunchdLegacySweep -- cure a service's legacy launchd label registrations."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Self, final

from punt_lux._launchctl import launchctl
from punt_lux._legacy_sweep import LegacyServiceOutcome, LegacySweepReport
from punt_lux._service_errors import ServiceMigrationError
from punt_lux._service_spec import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["LaunchdLegacySweep"]

# launchd deregisters a job asynchronously: `launchctl bootout` can return
# before the job actually leaves the domain, so an immediate `launchctl print`
# recheck can observe the job still registered even though the bootout is
# about to land. Poll briefly before declaring the sweep failed -- this is
# the exact race the self-upgrade path (`install()` deregistering its own
# running label before rewriting the plist) hits on every restart.
_BOOTOUT_POLL_INTERVAL_SECONDS = 0.2
_BOOTOUT_POLL_TIMEOUT_SECONDS = 2.0


@final
class LaunchdLegacySweep:
    """Deregister and delete plists left behind by a launchd label rename."""

    __slots__ = ("_dir", "_spec")
    _dir: Path
    _spec: ServiceSpec

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._dir = Path.home() / "Library" / "LaunchAgents"
        return self

    def is_clean(self) -> bool:
        """Return whether every legacy label is already clean, without mutating."""
        return self.diagnose().all_clean

    def diagnose(self) -> LegacySweepReport:
        """Non-mutating: build a report of every legacy label's current state."""
        outcomes = tuple(
            self._diagnose_one(label) for label in self._spec.legacy_launchd_labels
        )
        return LegacySweepReport(outcomes=outcomes)

    def sweep(self) -> LegacySweepReport:
        """Cure every legacy label; raise once with the full report if any fails."""
        outcomes = tuple(
            self._sweep_one(label) for label in self._spec.legacy_launchd_labels
        )
        report = LegacySweepReport(outcomes=outcomes)
        if not report.all_clean:
            msg = f"legacy launchd cleanup failed:\n{report.describe()}"
            raise ServiceMigrationError(msg)
        return report

    def _diagnose_one(self, label: str) -> LegacyServiceOutcome:
        clean = self._is_label_clean(label)
        return LegacyServiceOutcome(
            identifier=label,
            was_present=not clean,
            deregistered=False,
            config_removed=False,
            verified_clean=clean,
            fix_command=self._fix_command(label),
        )

    def _sweep_one(self, label: str) -> LegacyServiceOutcome:
        fix_command = self._fix_command(label)
        if self._is_label_clean(label):
            return LegacyServiceOutcome(
                identifier=label,
                was_present=False,
                deregistered=False,
                config_removed=False,
                verified_clean=True,
                fix_command=fix_command,
            )
        target = f"{launchctl.gui_domain()}/{label}"
        deregistered = launchctl.run(["launchctl", "bootout", target], verb="bootout")
        # The config file is only deleted once this re-check confirms the
        # deregister actually took -- a zero exit from bootout alone is not
        # proof; a mismatched launchd domain returns success while the job
        # stays registered (the exact ordering bug this primitive replaces).
        # bootout's deregistration lands asynchronously, so the recheck polls
        # briefly rather than firing once against a launchd that hasn't
        # caught up yet.
        if self._wait_until_deregistered(label):
            self._plist_path(label).unlink(missing_ok=True)
            return LegacyServiceOutcome(
                identifier=label,
                was_present=True,
                deregistered=deregistered,
                config_removed=True,
                verified_clean=True,
                fix_command=fix_command,
            )
        logger.warning("legacy launchd label %s still registered after bootout", label)
        return LegacyServiceOutcome(
            identifier=label,
            was_present=True,
            deregistered=deregistered,
            config_removed=False,
            verified_clean=False,
            fix_command=fix_command,
        )

    def _is_label_clean(self, label: str) -> bool:
        return not self._is_registered(label) and not self._plist_path(label).exists()

    def _wait_until_deregistered(self, label: str) -> bool:
        """Poll ``_is_registered`` briefly; bootout's effect lands async."""
        deadline = time.monotonic() + _BOOTOUT_POLL_TIMEOUT_SECONDS
        while True:
            if not self._is_registered(label):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(_BOOTOUT_POLL_INTERVAL_SECONDS)

    def _is_registered(self, label: str) -> bool:
        target = f"{launchctl.gui_domain()}/{label}"
        return launchctl.run(["launchctl", "print", target], verb="print")

    def _plist_path(self, label: str) -> Path:
        return self._dir / f"{label}.plist"

    @staticmethod
    def _fix_command(label: str) -> str:
        return f"launchctl bootout {launchctl.gui_domain()}/{label}"
