"""Platform-specific daemon lifecycle backends for luxd."""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self, final
from xml.sax.saxutils import escape as _xml_escape

logger = logging.getLogger(__name__)

_LABEL = "com.punt-labs.lux"


class ServiceBackend(ABC):
    """Platform-specific daemon lifecycle strategy."""

    @abstractmethod
    def install(self, exec_args: list[str]) -> None:
        """Register and start the daemon service."""

    @abstractmethod
    def uninstall(self) -> None:
        """Stop and remove the daemon service."""

    @abstractmethod
    def is_active(self) -> bool:
        """Return whether the daemon is currently running."""

    @abstractmethod
    def config_path(self) -> Path:
        """Return the path to the service config file."""


# ---------------------------------------------------------------------------
# macOS -- launchd
# ---------------------------------------------------------------------------


@final
class LaunchdBackend(ServiceBackend):  # pylint: disable=too-few-public-methods
    """Implement ServiceBackend for launchd (plist)."""

    __slots__ = ("_plist_path",)

    _plist_path: Path
    _DIR: Path = Path.home() / "Library" / "LaunchAgents"

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._plist_path = cls._DIR / f"{_LABEL}.plist"
        return self

    def config_path(self) -> Path:
        """Return the plist path."""
        return self._plist_path

    def is_active(self) -> bool:
        """Return whether the luxd launchd service is loaded."""
        result = subprocess.run(
            ["launchctl", "list", _LABEL],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def install(self, exec_args: list[str]) -> None:
        """Write the plist and load luxd into launchd."""
        from punt_lux.hub_paths import hub_log_dir

        hub_log_dir().mkdir(parents=True, exist_ok=True)
        self._DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

        # Unload first -- handles upgrades with a changed binary path.
        if self.is_active():
            result = subprocess.run(
                ["launchctl", "unload", "-w", str(self._plist_path)],
                check=False,
            )
            if result.returncode == 0:
                logger.info("Unloaded existing %s before upgrade", _LABEL)
            else:
                logger.warning(
                    "Could not unload %s (rc=%d) -- proceeding with load",
                    _LABEL,
                    result.returncode,
                )

        content = self._plist_content(exec_args)
        self._write_config_atomic(content)
        logger.info("Wrote %s", self._plist_path)

        subprocess.run(
            ["launchctl", "load", "-w", str(self._plist_path)],
            check=True,
        )
        logger.info("Loaded %s into launchd", _LABEL)

    def uninstall(self) -> None:
        """Unload luxd from launchd and remove the plist."""
        if self._plist_path.exists():
            result = subprocess.run(
                ["launchctl", "unload", "-w", str(self._plist_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "launchctl unload failed (rc=%d): %s",
                    result.returncode,
                    result.stderr.strip(),
                )
            self._plist_path.unlink()
            logger.info("Removed %s", self._plist_path)
        else:
            logger.info(
                "No plist found at %s -- nothing to uninstall",
                self._plist_path,
            )

    def _plist_content(self, exec_args: list[str]) -> str:
        """Generate the launchd plist XML for luxd."""
        program_args = "\n".join(
            f"        <string>{_xml_escape(a)}</string>" for a in exec_args
        )
        log_dir = Path.home() / ".punt-labs" / "lux" / "logs"
        return textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>{_LABEL}</string>
                <key>ProgramArguments</key>
                <array>
            {program_args}
                </array>
                <key>RunAtLoad</key>
                <true/>
                <key>KeepAlive</key>
                <true/>
                <key>StandardOutPath</key>
                <string>{log_dir}/luxd-stdout.log</string>
                <key>StandardErrorPath</key>
                <string>{log_dir}/luxd-stderr.log</string>
            </dict>
            </plist>
        """)

    def _write_config_atomic(self, content: str) -> None:
        """Atomically write config to the plist path."""
        tmp_path = self._plist_path.with_name(self._plist_path.name + ".tmp")
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
            tmp_path.replace(self._plist_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------------------
# Linux -- systemd user unit
# ---------------------------------------------------------------------------


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


def has_linger() -> bool:
    """Check if loginctl linger is enabled for the current user."""
    try:
        user = os.getlogin()
    except OSError:
        return True  # Can't check; don't warn
    try:
        result = subprocess.run(
            ["loginctl", "show-user", user, "--property=Linger"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return True  # No loginctl (container/minimal install); don't warn
    return "Linger=yes" in result.stdout
