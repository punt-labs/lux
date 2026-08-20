"""macOS launchd backend for luxd's daemon lifecycle."""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Self, final
from xml.sax.saxutils import escape as _xml_escape

from punt_lux._backends import ServiceBackend

logger = logging.getLogger(__name__)

_LABEL = "com.punt-labs.lux"

__all__ = ["LaunchdBackend"]


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
        from punt_lux.hub_paths import HubPaths

        HubPaths().log_dir.mkdir(parents=True, exist_ok=True)
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

    def stop(self) -> None:
        """Unload luxd from launchd, leaving the plist in place.

        ``KeepAlive`` means launchd respawns an unloaded-then-relaunched job on
        its own schedule only if re-loaded; a bare ``bootout``/``unload`` here
        stops the running process without touching the service registration,
        so ``lux hub start`` (or the next login) brings it back the same way
        ``install`` originally did.
        """
        if not self._plist_path.exists():
            logger.info("No plist found at %s -- nothing to stop", self._plist_path)
            return
        result = subprocess.run(
            ["launchctl", "unload", str(self._plist_path)],
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

    def start(self) -> None:
        """Re-load the installed plist into launchd, symmetric to :meth:`stop`.

        The plist must already exist -- :meth:`ServiceManager.start` checks
        that and reports the "run install" message before this ever runs.
        """
        result = subprocess.run(
            ["launchctl", "load", str(self._plist_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "launchctl load failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
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
