"""ServiceSpec — a service's identity across supervisors and its command line.

A value object naming the launchd label, systemd unit, description, binary,
extra args, and log file stems for one Lux service. The hub and the display
each get one; :class:`~punt_lux.service.ServiceManager` composes the pair.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import final

from punt_lux.luxd import DEFAULT_HUB_PORT

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
    log_stem: str
    cli_verb: str
    process_name: str
    legacy_launchd_labels: tuple[str, ...] = ()
    legacy_systemd_units: tuple[str, ...] = ()
    legacy_binary_names: tuple[str, ...] = ()
    # None: no fixed port to guard -- DISPLAY_SPEC's documented contract.
    health_port: int | None = None

    def resolve_exec_args(self) -> list[str]:
        """Return the command that launches this service.

        Resolves ``~/.local/bin/<binary_name>`` -- the uv-tool install
        symlink, stable across ``uv tool upgrade`` -- and refuses if missing.
        """
        local_bin = Path.home() / ".local" / "bin" / self.binary_name
        if not local_bin.exists():
            msg = (
                f"Cannot find {self.binary_name} binary at {local_bin}. "
                "Install lux first: uv tool install punt-lux"
            )
            raise RuntimeError(msg)
        logger.info("%s binary: %s (uv tool)", self.display_name, local_bin)
        return [str(local_bin), *self.extra_args]

    def log_stdout(self, log_dir: Path) -> Path:
        """Return the stdout log path for this service under ``log_dir``."""
        return log_dir / f"{self.log_stem}-stdout.log"

    def log_stderr(self, log_dir: Path) -> Path:
        """Return the stderr log path for this service under ``log_dir``."""
        return log_dir / f"{self.log_stem}-stderr.log"


HUB_SPEC: ServiceSpec = ServiceSpec(
    display_name="luxd",
    launchd_label="com.punt-labs.luxd-hub",
    systemd_unit="luxd-hub",
    systemd_description="Lux session hub daemon",
    binary_name="luxd-hub",
    extra_args=("--port", str(DEFAULT_HUB_PORT)),
    log_stem="luxd",
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
    log_stem="luxd-display",
    cli_verb="display",
    process_name="luxd-display",
)
