"""DoctorResult -- the outcome of ``lux hub doctor`` / ``lux display doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from punt_lux._legacy_sweep import LegacySweepReport
from punt_lux._port_guard import PortGuardResult

__all__ = ["DoctorResult"]

_CLEAN_PORT_STATUSES = ("free", "ours")


@final
@dataclass(frozen=True, slots=True)
class DoctorResult:
    """The outcome of one ``doctor`` run, ready for the CLI to print and exit on."""

    display_name: str
    process_name: str
    health_port: int | None  # None mirrors ServiceSpec: no fixed port to guard
    legacy: LegacySweepReport
    port: PortGuardResult
    repair_failed: bool

    @property
    def is_clean(self) -> bool:
        """Return whether both the legacy identifiers and the port are clean."""
        return self.legacy.all_clean and self.port.status in _CLEAN_PORT_STATUSES

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
        lines = [header, *self._legacy_lines(), *self._port_lines()]
        return "\n".join(lines)

    def _legacy_lines(self) -> list[str]:
        if not self.legacy.outcomes:
            return []
        if self.legacy.all_clean:
            return ["  legacy labels: none registered"]
        return [line for line in self.legacy.describe().splitlines() if line]

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
