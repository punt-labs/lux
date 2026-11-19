"""macOS launchd backend for Lux service lifecycle (hub or display)."""

from __future__ import annotations

import logging
import subprocess
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Self, final
from xml.sax.saxutils import escape as _xml_escape

from punt_lux._backends import ServiceBackend
from punt_lux._launchctl import launchctl
from punt_lux._launchd_plist import LaunchdPlist
from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._service_errors import ServiceMigrationError

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["LaunchdBackend"]


@final
class LaunchdBackend(ServiceBackend):  # pylint: disable=too-few-public-methods
    """Implement ServiceBackend for launchd (plist)."""

    __slots__ = ("_plist",)

    _plist: LaunchdPlist

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._plist = LaunchdPlist(spec)
        return self

    def config_path(self) -> Path:
        """Return the plist path."""
        return self._plist.path

    def is_active(self) -> bool:
        """Return whether the luxd launchd service is loaded."""
        result = subprocess.run(
            ["launchctl", "list", self._plist.spec.launchd_label],
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

        label = self._plist.spec.launchd_label
        desired_plist = self._plist_content()
        if self.is_active():
            if self._plist.installed_content() == desired_plist:
                logger.info("%s already installed and up to date; no-op", label)
                return True
            LaunchdLegacySweep(
                replace(self._plist.spec, legacy_launchd_labels=(label,))
            ).sweep()
            logger.info("Deregistered existing %s before upgrade", label)

        self._plist.write(desired_plist)
        logger.info("Wrote %s", self._plist.path)
        if not self._bootstrap():
            msg = f"failed to bootstrap {label} into launchd"
            raise ServiceMigrationError(msg)
        logger.info("Bootstrapped %s into launchd", label)
        return False

    def enable_autostart(self) -> bool:
        return launchctl.run(["launchctl", "enable", self._plist.target], verb="enable")

    def uninstall(self) -> None:
        """Boot the job out of launchd (if loaded) and remove the plist."""
        if not self._plist.path.exists():
            logger.info("No plist at %s; nothing to uninstall", self._plist.path)
            return
        target = self._plist.target
        launchctl.run(["launchctl", "bootout", target], verb="bootout")
        self._plist.path.unlink()
        logger.info("Removed %s", self._plist.path)

    def stop(self) -> bool:
        """Boot out registration (plist stays); missing config is a no-op.

        KeepAlive respawns plain SIGTERM; deregistration is the actual stop.
        """
        if not self._plist.path.exists():
            logger.info("No plist found at %s -- nothing to stop", self._plist.path)
            return True
        target = self._plist.target
        return launchctl.run(["launchctl", "bootout", target], verb="bootout")

    def restart(self) -> bool:
        """Atomically kill-and-respawn under the same plist — one call, no pid file."""
        target = self._plist.target
        return launchctl.run(
            ["launchctl", "kickstart", "-k", target],
            verb="kickstart",
        )

    def start(self) -> bool:
        """Kickstart registration without -k, else bootstrap installed config.

        Clean Display exit retains its job; repeated bootstrap fails with rc=5.
        A plain kickstart leaves any already-running job alone.
        """
        if self.is_active():  # this backend's existing contract means loaded
            target = self._plist.target
            return launchctl.run(["launchctl", "kickstart", target], verb="kickstart")
        return self._bootstrap()

    def _bootstrap(self) -> bool:
        return launchctl.run(
            ["launchctl", "bootstrap", launchctl.gui_domain(), str(self._plist.path)],
            verb="bootstrap",
        )

    def _plist_content(self) -> str:
        """Generate the launchd plist XML for the service."""
        exec_args = self._plist.spec.resolve_exec_args()
        program_args = "\n".join(
            f"        <string>{_xml_escape(a)}</string>" for a in exec_args
        )
        log_dir = Path.home() / ".punt-labs" / "lux" / "logs"
        stdout = self._plist.spec.log_stdout(log_dir)
        stderr = self._plist.spec.log_stderr(log_dir)
        return textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>{self._plist.spec.launchd_label}</string>
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
        return crash_only if self._plist.spec.restart_on_crash_only else always
