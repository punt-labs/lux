"""macOS launchd backend for Lux service lifecycle (hub or display)."""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Self, final
from xml.sax.saxutils import escape as _xml_escape

from punt_lux._atomic_write import write_config_atomic
from punt_lux._backends import ServiceBackend
from punt_lux._launchctl import gui_domain, launchctl
from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._service_errors import ServiceMigrationError

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["LaunchdBackend"]


@final
class LaunchdBackend(ServiceBackend):  # pylint: disable=too-few-public-methods
    """Implement ServiceBackend for launchd (plist)."""

    __slots__ = ("_dir", "_plist_path", "_spec")

    _dir: Path
    _plist_path: Path
    _spec: ServiceSpec

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        # Resolved here, not as a class attribute -- a class body runs once
        # at import time, binding the real Path.home() forever. Resolving it
        # per-instance is what makes Path.home() patchable in tests.
        self._dir = Path.home() / "Library" / "LaunchAgents"
        self._plist_path = self._dir / f"{spec.launchd_label}.plist"
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
        """Write the plist and bootstrap the service into launchd.

        Curing a stale registration under this service's OWN label (an
        in-place binary-path upgrade) uses the same bootout-and-verify
        discipline as a renamed predecessor's cleanup
        (:class:`~punt_lux._legacy_sweep_launchd.LaunchdLegacySweep`) --
        fatal on failure, never a warn-and-continue fallthrough onto a
        supervisor call that may silently no-op.
        """
        from punt_lux.hub_paths import HubPaths

        HubPaths().log_dir.mkdir(parents=True, exist_ok=True)
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)

        label = self._spec.launchd_label
        if self.is_active():
            self._self_upgrade_sweep().sweep()
            logger.info("Deregistered existing %s before upgrade", label)

        write_config_atomic.write(self._plist_path, self._plist_content())
        logger.info("Wrote %s", self._plist_path)
        if not launchctl.run(
            ["launchctl", "bootstrap", gui_domain(), str(self._plist_path)],
            verb="bootstrap",
        ):
            msg = f"failed to bootstrap {label} into launchd"
            raise ServiceMigrationError(msg)
        logger.info("Bootstrapped %s into launchd", label)

    def _self_upgrade_sweep(self) -> LaunchdLegacySweep:
        """Return a sweep targeting this service's OWN label.

        Reuses the legacy-sweep primitive against the current label rather
        than a historical one -- the ordering and verification discipline a
        stale in-place registration needs is identical either way.
        """
        return LaunchdLegacySweep(
            replace(self._spec, legacy_launchd_labels=(self._spec.launchd_label,))
        )

    def uninstall(self) -> None:
        """Boot the job out of launchd (if loaded) and remove the plist."""
        if not self._plist_path.exists():
            logger.info(
                "No plist found at %s -- nothing to uninstall",
                self._plist_path,
            )
            return
        target = f"{gui_domain()}/{self._spec.launchd_label}"
        launchctl.run(["launchctl", "bootout", target], verb="bootout")
        self._plist_path.unlink()
        logger.info("Removed %s", self._plist_path)

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
        return launchctl.run(["launchctl", "bootout", target], verb="bootout")

    def restart(self) -> bool:
        """Atomically kill-and-respawn the job under launchd.

        ``launchctl kickstart -k`` sends the current instance a signal and
        launchd starts a fresh one under the same plist — one supervisor
        call, no pid file, no gap where the daemon is deregistered. The
        supervisor already knows the pid, so a restart is not a signal-based
        handshake with a pid file the daemon does not itself keep current.
        """
        target = f"{self._gui_domain()}/{self._spec.launchd_label}"
        return launchctl.run(
            ["launchctl", "kickstart", "-k", target],
            verb="kickstart",
        )

    def start(self) -> bool:
        """Re-bootstrap the installed plist into launchd, symmetric to :meth:`stop`.

        The plist must already exist -- :meth:`ServiceManager.start` checks
        that and reports the "run install" message before this ever runs.
        ``bootstrap``, not ``load``: the counterpart to ``bootout`` in the same
        modern subsystem, so a service this backend stopped can be started
        again without relying on the legacy load/unload shim.
        """
        return launchctl.run(
            ["launchctl", "bootstrap", self._gui_domain(), str(self._plist_path)],
            verb="bootstrap",
        )

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
        legacy = self._dir / "com.punt-labs.lux.plist"
        if not legacy.exists():
            return
        launchctl.run(["launchctl", "unload", "-w", str(legacy)], verb="unload")
        legacy.unlink(missing_ok=True)
        logger.info("Removed legacy plist %s", legacy)
