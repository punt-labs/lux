"""ServiceSpec — a service's identity across supervisors and its command line.

Names the launchd label, systemd unit, binary, and args for one
Lux service; the hub and display each get one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import final

from punt_lux.kernel.hub_defaults import DEFAULT_HUB_PORT

logger = logging.getLogger(__name__)

__all__ = ["DISPLAY_SPEC", "HUB_SPEC", "ServiceSpec"]


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
    # None: no fixed port to guard -- DISPLAY_SPEC's documented contract.
    health_port: int | None = None
    # True (DISPLAY_SPEC only): a clean exit is operator-initiated under the
    # demand-driven design, so the supervisor restarts a crash, never a stop.
    restart_on_crash_only: bool = False

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


HUB_SPEC: ServiceSpec = ServiceSpec(
    display_name="luxd",
    launchd_label="com.punt-labs.luxd-hub",
    systemd_unit="luxd-hub",
    systemd_description="Lux session hub daemon",
    binary_name="luxd-hub",
    extra_args=("--port", str(DEFAULT_HUB_PORT)),
    cli_verb="hub",
    process_name="luxd-hub",
    legacy_launchd_labels=("com.punt-labs.lux",),
    legacy_systemd_units=("lux",),
    legacy_binary_names=("luxd",),
    health_port=DEFAULT_HUB_PORT,
)


DISPLAY_SPEC: ServiceSpec = ServiceSpec(
    display_name="luxd-display",
    launchd_label="com.punt-labs.luxd-display",
    systemd_unit="luxd-display",
    systemd_description="Lux display window server",
    binary_name="luxd-display",
    extra_args=(),
    cli_verb="display",
    process_name="luxd-display",
    restart_on_crash_only=True,
)
