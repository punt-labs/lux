"""Linux systemd user-unit backend for Lux service lifecycle (hub or display)."""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from punt_lux._backends import ServiceBackend

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["SystemdBackend"]


@final
class SystemdBackend(ServiceBackend):  # pylint: disable=too-few-public-methods
    """Implement ServiceBackend for systemd user units."""

    __slots__ = ("_spec", "_unit_path")

    _spec: ServiceSpec
    _unit_path: Path
    _DIR: Path = Path.home() / ".config" / "systemd" / "user"

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._unit_path = cls._DIR / f"{spec.systemd_unit}.service"
        return self

    def config_path(self) -> Path:
        """Return the unit file path."""
        return self._unit_path

    def is_active(self) -> bool:
        """Return whether the systemd user service is active."""
        result = subprocess.run(
            ["systemctl", "--user", "is-active", self._spec.systemd_unit],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() == "active"

    def install(self) -> None:
        """Write the unit file, reload systemd, and enable+start the service."""
        self._DIR.mkdir(parents=True, exist_ok=True)
        self._remove_legacy_units()
        self._write_config_atomic(self._unit_content())
        logger.info("Wrote %s", self._unit_path)

        unit = self._spec.systemd_unit
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", unit], check=True)
        subprocess.run(["systemctl", "--user", "restart", unit], check=True)
        logger.info("Enabled and restarted %s.service", unit)

    def uninstall(self) -> None:
        """Stop, disable, and remove the systemd unit."""
        if self._unit_path.exists():
            self._disable_now(self._spec.systemd_unit)
            self._unit_path.unlink()
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            logger.info("Removed %s", self._unit_path)
        else:
            logger.info(
                "No unit found at %s -- nothing to uninstall",
                self._unit_path,
            )

    def stop(self) -> bool:
        """Stop the unit; it stays enabled for the next start/boot."""
        return self._run_verb("stop")

    def start(self) -> bool:
        """Start the installed unit, symmetric to :meth:`stop`."""
        return self._run_verb("start")

    def _run_verb(self, verb: str) -> bool:
        """Invoke ``systemctl --user <verb>`` on this service; log on failure."""
        result = subprocess.run(
            ["systemctl", "--user", verb, self._spec.systemd_unit],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "systemctl %s failed (rc=%d): %s",
                verb,
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0

    def _remove_legacy_units(self) -> None:
        """Disable and delete units shipped under the pre-rename name.

        A rename train leaves the old unit behind, and both the old and new
        user units would race to bind the same port at next boot. The
        current hub unit is ``luxd-hub``; the pre-rename unit was ``lux``.
        Only the hub install cleans it up; the display had no prior unit.
        Mirrors ``LaunchdBackend._remove_legacy_plists``.
        """
        if self._spec.systemd_unit != "luxd-hub":
            return
        legacy = self._DIR / "lux.service"
        if not legacy.exists():
            return
        self._disable_now("lux.service")
        legacy.unlink(missing_ok=True)
        logger.info("Removed legacy unit %s", legacy)

    @staticmethod
    def _disable_now(unit: str) -> None:
        """Run ``systemctl --user disable --now <unit>``, tolerating absence."""
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", unit],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _escape_arg(arg: str) -> str:
        """Escape ``arg`` for systemd ExecStart (its own parser, not POSIX)."""
        escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _unit_content(self) -> str:
        """Generate the systemd unit file content for the service."""
        exec_args = self._spec.resolve_exec_args()
        exec_start = " ".join(self._escape_arg(a) for a in exec_args)
        return textwrap.dedent(f"""\
            [Unit]
            Description={self._spec.systemd_description}
            After=network.target

            [Service]
            ExecStart={exec_start}
            Restart=on-failure
            RestartSec=5

            [Install]
            WantedBy=default.target
        """)

    def _write_config_atomic(self, content: str) -> None:
        """Atomically write config to the unit path."""
        tmp_path = self._unit_path.with_name(self._unit_path.name + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(str(tmp_path), flags, 0o600)
        try:
            f = os.fdopen(fd, "w")
        except BaseException:
            os.close(fd)
            tmp_path.unlink(missing_ok=True)
            raise
        try:
            with f:
                f.write(content)
            tmp_path.replace(self._unit_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
