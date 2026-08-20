"""Linux systemd user-unit backend for luxd's daemon lifecycle."""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Self, final

from punt_lux._backends import ServiceBackend

logger = logging.getLogger(__name__)

__all__ = ["SystemdBackend"]


@final
class SystemdBackend(ServiceBackend):  # pylint: disable=too-few-public-methods
    """Implement ServiceBackend for systemd user units."""

    __slots__ = ("_unit_path",)

    _unit_path: Path
    _DIR: Path = Path.home() / ".config" / "systemd" / "user"

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._unit_path = cls._DIR / "lux.service"
        return self

    def config_path(self) -> Path:
        """Return the unit file path."""
        return self._unit_path

    def is_active(self) -> bool:
        """Return whether the luxd systemd user service is active."""
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "lux"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() == "active"

    def install(self, exec_args: list[str]) -> None:
        """Write the unit file, reload systemd, and enable+start luxd."""
        self._DIR.mkdir(parents=True, exist_ok=True)
        content = self._unit_content(exec_args)
        self._write_config_atomic(content)
        logger.info("Wrote %s", self._unit_path)

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "lux"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "lux"], check=True)
        logger.info("Enabled and restarted lux.service")

    def uninstall(self) -> None:
        """Stop, disable, and remove the systemd unit."""
        if self._unit_path.exists():
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "lux"],
                check=False,
            )
            self._unit_path.unlink()
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            logger.info("Removed %s", self._unit_path)
        else:
            logger.info(
                "No unit found at %s -- nothing to uninstall",
                self._unit_path,
            )

    def stop(self) -> bool:
        """Stop the systemd unit, leaving it enabled for the next start/boot."""
        result = subprocess.run(
            ["systemctl", "--user", "stop", "lux"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "systemctl stop failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0

    def start(self) -> bool:
        """Start the installed systemd unit, symmetric to :meth:`stop`.

        The unit must already exist -- :meth:`ServiceManager.start` checks
        that and reports the "run install" message before this ever runs.
        """
        result = subprocess.run(
            ["systemctl", "--user", "start", "lux"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "systemctl start failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0

    @staticmethod
    def _escape_arg(arg: str) -> str:
        """Escape a single argument for systemd ExecStart.

        systemd uses its own parser, not POSIX shell. Double-quote the
        value and backslash-escape embedded double-quotes and backslashes.
        """
        escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _unit_content(self, exec_args: list[str]) -> str:
        """Generate the systemd unit file content for luxd."""
        exec_start = " ".join(self._escape_arg(a) for a in exec_args)
        return textwrap.dedent(f"""\
            [Unit]
            Description=Lux session hub daemon
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
