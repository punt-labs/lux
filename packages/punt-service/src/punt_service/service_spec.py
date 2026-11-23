"""ServiceSpec — a service's identity across supervisors and its command line.

Names the launchd label, systemd unit, binary, and args for one
managed service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import final

logger = logging.getLogger(__name__)

__all__ = ["ServiceSpec"]


@final
@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """One service's launchd/systemd identity and its executable command."""

    display_name: str
    launchd_label: str
    systemd_unit: str
    systemd_description: str
    binary_name: str
    extra_args: tuple[str, ...]
    cli_verb: str
    process_name: str
    legacy_launchd_labels: tuple[str, ...] = ()
    legacy_systemd_units: tuple[str, ...] = ()
    legacy_binary_names: tuple[str, ...] = ()
    # None: no fixed port to guard.
    health_port: int | None = None
    # A clean exit is operator-initiated; restart crashes, never a clean stop.
    restart_on_crash_only: bool = False
    cli_name: str = "service"
    log_path: str | None = None

    def failure_message(self, action: str) -> str:
        """Describe a failed supervisor action with optional product diagnostics."""
        message = f"{self.display_name} {action} failed."
        return (
            message
            if self.log_path is None
            else f"{message} See {self.log_path} for details."
        )

    def resolve_exec_args(self) -> list[str]:
        """Return the command line, resolving the stable uv-tool-install symlink."""
        local_bin = self._installed_binary()
        logger.info("%s binary: %s (uv tool)", self.display_name, local_bin)
        return [str(local_bin), *self.extra_args]

    def _installed_binary(self) -> Path:
        """Find the executable at its stable installation path."""
        local_bin = self._binary_path
        if not local_bin.exists():
            msg = (
                f"Cannot find {self.binary_name} binary at {local_bin}. "
                f"Install the {self.binary_name} executable in ~/.local/bin first."
            )
            raise RuntimeError(msg)
        return local_bin

    @property
    def _binary_path(self) -> Path:
        return Path.home() / ".local" / "bin" / self.binary_name
