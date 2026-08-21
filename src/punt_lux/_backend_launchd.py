"""macOS launchd backend for Lux service lifecycle (hub or display)."""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Self, final
from xml.sax.saxutils import escape as _xml_escape

from punt_lux._backends import ServiceBackend

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["LaunchdBackend"]


@final
class LaunchdBackend(ServiceBackend):  # pylint: disable=too-few-public-methods
    """Implement ServiceBackend for launchd (plist)."""

    __slots__ = ("_plist_path", "_spec")

    _plist_path: Path
    _spec: ServiceSpec
    _DIR: Path = Path.home() / "Library" / "LaunchAgents"

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._plist_path = cls._DIR / f"{spec.launchd_label}.plist"
        return self

    def config_path(self) -> Path:
        """Return the plist path."""
        return self._plist_path

    def is_active(self) -> bool:
        """Return whether the luxd launchd service is loaded."""
        result = subprocess.run(
            ["launchctl", "list", self._spec.launchd_label],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def install(self) -> None:
        """Write the plist and load the service into launchd."""
        from punt_lux.hub_paths import HubPaths

        HubPaths().log_dir.mkdir(parents=True, exist_ok=True)
        self._DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._remove_legacy_plists()

        # Unload first -- handles upgrades with a changed binary path.
        label = self._spec.launchd_label
        if self.is_active():
            result = subprocess.run(
                ["launchctl", "unload", "-w", str(self._plist_path)],
                check=False,
            )
            if result.returncode == 0:
                logger.info("Unloaded existing %s before upgrade", label)
            else:
                logger.warning(
                    "Could not unload %s (rc=%d) -- proceeding with load",
                    label,
                    result.returncode,
                )

        self._write_config_atomic(self._plist_content())
        logger.info("Wrote %s", self._plist_path)
        subprocess.run(
            ["launchctl", "load", "-w", str(self._plist_path)],
            check=True,
        )
        logger.info("Loaded %s into launchd", label)

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

    def stop(self) -> bool:
        """Boot the job out of launchd (plist stays); a missing plist is a no-op.

        ``bootout``, not ``unload``: with ``KeepAlive=true`` (every plist this
        backend writes), ``launchctl stop`` sends SIGTERM and launchd
        immediately respawns the job per the KeepAlive contract — the daemon
        never actually stops. ``bootout`` deregisters the job from the GUI
        domain outright, so nothing is left to respawn it.
        """
        if not self._plist_path.exists():
            logger.info("No plist found at %s -- nothing to stop", self._plist_path)
            return True
        target = f"{self._gui_domain()}/{self._spec.launchd_label}"
        result = subprocess.run(
            ["launchctl", "bootout", target],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "launchctl bootout failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0

    def start(self) -> bool:
        """Re-bootstrap the installed plist into launchd, symmetric to :meth:`stop`.

        The plist must already exist -- :meth:`ServiceManager.start` checks
        that and reports the "run install" message before this ever runs.
        ``bootstrap``, not ``load``: the counterpart to ``bootout`` in the same
        modern subsystem, so a service this backend stopped can be started
        again without relying on the legacy load/unload shim.
        """
        result = subprocess.run(
            ["launchctl", "bootstrap", self._gui_domain(), str(self._plist_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "launchctl bootstrap failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
        return result.returncode == 0

    @staticmethod
    def _gui_domain() -> str:
        """Return this user's launchd GUI domain target, e.g. ``gui/501``."""
        return f"gui/{os.getuid()}"

    def _plist_content(self) -> str:
        """Generate the launchd plist XML for the service."""
        exec_args = self._spec.resolve_exec_args()
        program_args = "\n".join(
            f"        <string>{_xml_escape(a)}</string>" for a in exec_args
        )
        log_dir = Path.home() / ".punt-labs" / "lux" / "logs"
        stdout = self._spec.log_stdout(log_dir)
        stderr = self._spec.log_stderr(log_dir)
        return textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>{self._spec.launchd_label}</string>
                <key>ProgramArguments</key>
                <array>
            {program_args}
                </array>
                <key>RunAtLoad</key>
                <true/>
                <key>KeepAlive</key>
                <true/>
                <key>StandardOutPath</key>
                <string>{stdout}</string>
                <key>StandardErrorPath</key>
                <string>{stderr}</string>
            </dict>
            </plist>
        """)

    def _remove_legacy_plists(self) -> None:
        """Unload and delete plists shipped under old labels for this service.

        A rename train leaves the old plist behind, and both the old and new
        LaunchAgents would race to bind the same port at next login. The
        current hub label is ``com.punt-labs.luxd-hub``; the pre-rename label
        was ``com.punt-labs.lux``. Only the hub install cleans it up; the
        display had no prior label.
        """
        if self._spec.launchd_label != "com.punt-labs.luxd-hub":
            return
        legacy = self._DIR / "com.punt-labs.lux.plist"
        if not legacy.exists():
            return
        subprocess.run(
            ["launchctl", "unload", "-w", str(legacy)],
            capture_output=True,
            text=True,
            check=False,
        )
        legacy.unlink(missing_ok=True)
        logger.info("Removed legacy plist %s", legacy)

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
