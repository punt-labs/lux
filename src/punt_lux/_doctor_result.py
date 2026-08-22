"""DoctorResult -- the outcome of ``lux hub doctor`` / ``lux display doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux._binary_sweep import BinarySweepReport
from punt_lux._legacy_sweep import LegacySweepReport
from punt_lux._port_guard import PortGuardResult
from punt_lux._service_errors import PortConflictError, ServiceMigrationError

if TYPE_CHECKING:
    from punt_lux._binary_sweep import BinarySweep
    from punt_lux._legacy_sweep import LegacySweep
    from punt_lux._port_guard import PortGuard
    from punt_lux._service_spec import ServiceSpec

__all__ = ["DoctorCheckers", "DoctorResult"]

_CLEAN_PORT_STATUSES = ("free", "ours")


@final
@dataclass(frozen=True, slots=True)
class DoctorCheckers:
    """The sweep/guard objects `install()` and `doctor` share for one service."""

    legacy_sweep: LegacySweep
    binary_sweep: BinarySweep
    port_guard: PortGuard
    spec: ServiceSpec


@final
@dataclass(frozen=True, slots=True)
class DoctorResult:
    """The outcome of one ``doctor`` run, ready for the CLI to print and exit on."""

    display_name: str
    process_name: str
    health_port: int | None  # None mirrors ServiceSpec: no fixed port to guard
    legacy: LegacySweepReport
    binary: BinarySweepReport
    port: PortGuardResult
    repair_failed: bool

    @classmethod
    def diagnose(cls, checkers: DoctorCheckers) -> Self:
        """Build a result from the non-mutating query methods only.

        The ``lux <verb> doctor`` (no ``--fix``) branch -- zero mutating
        calls, safe to run repeatedly.
        """
        spec = checkers.spec
        return cls(
            display_name=spec.display_name,
            process_name=spec.process_name,
            health_port=spec.health_port,
            legacy=checkers.legacy_sweep.diagnose(),
            binary=checkers.binary_sweep.diagnose(),
            port=checkers.port_guard.check(),
            repair_failed=False,
        )

    @classmethod
    def repair(cls, checkers: DoctorCheckers) -> Self:
        """Build a result by curing what's dirty, same objects `install()` uses.

        The ``lux <verb> doctor --fix`` branch. A failed cure is folded into
        ``repair_failed`` rather than propagated -- the CLI renders and
        chooses its exit code from the result, it never catches here.
        """
        spec = checkers.spec
        legacy, legacy_failed = cls._repair_legacy(checkers.legacy_sweep)
        binary, binary_failed = cls._repair_binary(checkers.binary_sweep)
        port, port_failed = cls._repair_port(checkers.port_guard, spec)
        return cls(
            display_name=spec.display_name,
            process_name=spec.process_name,
            health_port=spec.health_port,
            legacy=legacy,
            binary=binary,
            port=port,
            repair_failed=legacy_failed or binary_failed or port_failed,
        )

    @staticmethod
    def _repair_legacy(legacy_sweep: LegacySweep) -> tuple[LegacySweepReport, bool]:
        try:
            return legacy_sweep.sweep(), False
        except ServiceMigrationError:
            return legacy_sweep.diagnose(), True

    @staticmethod
    def _repair_binary(binary_sweep: BinarySweep) -> tuple[BinarySweepReport, bool]:
        try:
            return binary_sweep.sweep(), False
        except ServiceMigrationError:
            return binary_sweep.diagnose(), True

    @staticmethod
    def _repair_port(
        port_guard: PortGuard, spec: ServiceSpec
    ) -> tuple[PortGuardResult, bool]:
        port = port_guard.check()
        if spec.health_port is None or port.status in _CLEAN_PORT_STATUSES:
            return port, False
        try:
            port_guard.guard()
            return port_guard.check(), False
        except PortConflictError:
            return port, True

    @property
    def is_clean(self) -> bool:
        """Return whether the legacy identifiers, binaries, and port are all clean."""
        return (
            self.legacy.all_clean
            and self.binary.all_clean
            and self.port.status in _CLEAN_PORT_STATUSES
        )

    @property
    def exit_code(self) -> int:
        """0 clean; 1 dirty with no repair attempted; 2 a repair attempt failed."""
        if self.repair_failed:
            return 2
        return 0 if self.is_clean else 1

    def render(self) -> str:
        """Render the multi-line report `lux <verb> doctor` echoes."""
        header = f"{self.display_name}: {'clean' if self.is_clean else 'DIRTY'}"
        if self.repair_failed:
            header += " -- automatic repair failed"
        lines = [
            header,
            *self._legacy_lines(),
            *self._binary_lines(),
            *self._port_lines(),
        ]
        return "\n".join(lines)

    def _legacy_lines(self) -> list[str]:
        if not self.legacy.outcomes:
            return []
        if self.legacy.all_clean:
            return ["  legacy registrations: none"]
        return [line for line in self.legacy.describe().splitlines() if line]

    def _binary_lines(self) -> list[str]:
        if not self.binary.outcomes:
            return []
        if self.binary.all_clean:
            return ["  legacy binaries: none present"]
        return [line for line in self.binary.describe().splitlines() if line]

    def _port_lines(self) -> list[str]:
        if self.health_port is None:
            return []
        if self.port.status == "free":
            return [f"  port {self.health_port}: free"]
        if self.port.status == "ours":
            owner = f"{self.process_name} (pid {self.port.pid})"
            return [f"  port {self.health_port}: owned by {owner}"]
        if self.port.status == "foreign":
            held_by = f"pid {self.port.pid} (not {self.process_name})"
            return [
                f"  port {self.health_port}: held by {held_by}",
                f"    inspect: lsof -nP -iTCP:{self.health_port} -sTCP:LISTEN",
            ]
        return [f"  port {self.health_port}: could not verify (lsof not found on PATH)"]
