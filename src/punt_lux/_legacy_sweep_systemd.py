"""SystemdLegacySweep -- cure a service's legacy systemd unit registrations."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Self, final

from punt_lux._legacy_sweep import LegacyServiceOutcome, LegacySweepReport
from punt_lux._service_errors import ServiceMigrationError
from punt_lux._service_spec import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["SystemdLegacySweep"]

# ``systemctl is-active`` returns 0 for "active" and "activating"; any other
# exit code (inactive, failed, deactivating, unit-not-found) means the unit
# is quiesced. ``status`` cannot be used for this check because it returns 0
# for a disabled+inactive unit whose file is still on disk -- and that file
# is exactly what a sweep needs to remove.
_ACTIVE = 0


@final
class SystemdLegacySweep:
    """Disable and delete units left behind by a systemd unit rename."""

    __slots__ = ("_dir", "_spec")
    _dir: Path
    _spec: ServiceSpec

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._dir = Path.home() / ".config" / "systemd" / "user"
        return self

    def is_clean(self) -> bool:
        """Return whether every legacy unit is already clean, without mutating."""
        return self.diagnose().all_clean

    def diagnose(self) -> LegacySweepReport:
        """Non-mutating: build a report of every legacy unit's current state."""
        outcomes = tuple(
            self._diagnose_one(unit) for unit in self._spec.legacy_systemd_units
        )
        return LegacySweepReport(outcomes=outcomes)

    def sweep(self) -> LegacySweepReport:
        """Cure every legacy unit; raise once with the full report if any fails."""
        outcomes = tuple(
            self._sweep_one(unit) for unit in self._spec.legacy_systemd_units
        )
        report = LegacySweepReport(outcomes=outcomes)
        if not report.all_clean:
            msg = f"legacy systemd cleanup failed:\n{report.describe()}"
            raise ServiceMigrationError(msg)
        return report

    def _diagnose_one(self, unit: str) -> LegacyServiceOutcome:
        clean = self._is_unit_clean(unit)
        return LegacyServiceOutcome(
            identifier=unit,
            was_present=not clean,
            deregistered=False,
            config_removed=False,
            verified_clean=clean,
            fix_command=self._fix_command(unit),
        )

    def _sweep_one(self, unit: str) -> LegacyServiceOutcome:
        fix_command = self._fix_command(unit)
        if self._is_unit_clean(unit):
            return LegacyServiceOutcome(
                identifier=unit,
                was_present=False,
                deregistered=False,
                config_removed=False,
                verified_clean=True,
                fix_command=fix_command,
            )
        result = subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{unit}.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        deregistered = result.returncode == 0
        # The unit file is only deleted once ``is-active`` confirms the unit
        # is quiesced -- the same ordering discipline as the launchd sweep,
        # so a lying disable exit code never orphans a live process. Once
        # the file is gone, ``daemon-reload`` makes systemd forget the unit
        # entirely; without it, a follow-up sweep would still see the unit
        # in ``is-enabled`` output.
        if not self._is_active(unit):
            self._unit_path(unit).unlink(missing_ok=True)
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True,
                check=False,
            )
            return LegacyServiceOutcome(
                identifier=unit,
                was_present=True,
                deregistered=deregistered,
                config_removed=True,
                verified_clean=True,
                fix_command=fix_command,
            )
        logger.warning("legacy systemd unit %s still active after disable", unit)
        return LegacyServiceOutcome(
            identifier=unit,
            was_present=True,
            deregistered=deregistered,
            config_removed=False,
            verified_clean=False,
            fix_command=fix_command,
        )

    def _is_unit_clean(self, unit: str) -> bool:
        return not self._is_active(unit) and not self._unit_path(unit).exists()

    def _is_active(self, unit: str) -> bool:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", f"{unit}.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == _ACTIVE

    def _unit_path(self, unit: str) -> Path:
        return self._dir / f"{unit}.service"

    @staticmethod
    def _fix_command(unit: str) -> str:
        return f"systemctl --user disable --now {unit}.service"
