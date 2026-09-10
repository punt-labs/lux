"""macOS launchd backend for Lux service lifecycle (hub or display)."""

from __future__ import annotations

import logging
import subprocess
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Self, final
from xml.sax.saxutils import escape as _xml_escape

from punt_lux._atomic_write import write_config_atomic
from punt_lux._backends import ServiceBackend
from punt_lux._launchctl import launchctl
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

    def install(self) -> bool:
        """Write the plist and bootstrap the service into launchd.

        Returns whether this call was a no-op: already active under the
        plist content we would write anyway. A live long-lived MCP daemon
        may never actually exit on SIGTERM (unbounded uvicorn shutdown
        window), so reinstalling unchanged must never bootout-then-bootstrap
        the same thing back (lux-94p0). A genuine content change still uses
        :class:`~punt_lux._legacy_sweep_launchd.LaunchdLegacySweep`'s
        bootout-and-verify discipline, fatal on failure.
        """
        from punt_lux.hub_paths import HubPaths

        HubPaths().log_dir.mkdir(parents=True, exist_ok=True)
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)

        label = self._spec.launchd_label
        desired_plist = self._plist_content()
        if self.is_active():
            unchanged = (
                self._plist_path.exists()
                and self._plist_path.read_text() == desired_plist
            )
            if unchanged:
                logger.info("%s already installed and up to date; no-op", label)
                return True
            self._self_upgrade_sweep().sweep()
            logger.info("Deregistered existing %s before upgrade", label)

        write_config_atomic.write(self._plist_path, desired_plist)
        logger.info("Wrote %s", self._plist_path)
        if not launchctl.run(
            ["launchctl", "bootstrap", launchctl.gui_domain(), str(self._plist_path)],
            verb="bootstrap",
        ):
            msg = f"failed to bootstrap {label} into launchd"
            raise ServiceMigrationError(msg)
        logger.info("Bootstrapped %s into launchd", label)
        return False

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
        target = f"{launchctl.gui_domain()}/{self._spec.launchd_label}"
        launchctl.run(["launchctl", "bootout", target], verb="bootout")
        self._plist_path.unlink()
        logger.info("Removed %s", self._plist_path)

    def stop(self) -> bool:
        """Boot the job out of launchd (plist stays); a missing plist is a no-op.

        ``bootout``, not ``unload``: KeepAlive respawns the job on a plain
        SIGTERM, so only deregistering it from the GUI domain actually stops it.
        """
        if not self._plist_path.exists():
            logger.info("No plist found at %s -- nothing to stop", self._plist_path)
            return True
        target = f"{launchctl.gui_domain()}/{self._spec.launchd_label}"
        return launchctl.run(["launchctl", "bootout", target], verb="bootout")

    def restart(self) -> bool:
        """Atomically kill-and-respawn under the same plist — one call, no pid file."""
        target = f"{launchctl.gui_domain()}/{self._spec.launchd_label}"
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
            ["launchctl", "bootstrap", launchctl.gui_domain(), str(self._plist_path)],
            verb="bootstrap",
        )

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
            {self._keep_alive_block()}
                <key>StandardOutPath</key>
                <string>{stdout}</string>
                <key>StandardErrorPath</key>
                <string>{stderr}</string>
            </dict>
            </plist>
        """)

    def _keep_alive_block(self) -> str:
        """Return the ``KeepAlive`` stanza: bare, or crash-only per the spec.

        Bare ``<true/>`` respawns on any exit, including a clean one — right
        for the always-on Hub, wrong for the demand-driven display, whose own
        clean exit is operator-initiated (design §4) and must not respawn.
        """
        crash_only = (
            "    <key>KeepAlive</key>\n"
            "    <dict>\n"
            "        <key>SuccessfulExit</key>\n"
            "        <false/>\n"
            "    </dict>"
        )
        always = "    <key>KeepAlive</key>\n    <true/>"
        return crash_only if self._spec.restart_on_crash_only else always
