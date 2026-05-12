"""Daemon lifecycle management for luxd.

Provides ``install`` and ``uninstall`` commands that register luxd as a
system service (launchd on macOS, systemd on Linux) so the daemon starts
at login and restarts on crash.

The service runs ``luxd --port 8430`` using the installed ``luxd``
binary (from ``uv tool install``), never ``sys.executable``.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from punt_lux.hub import DEFAULT_HUB_PORT

logger = logging.getLogger(__name__)

_LABEL = "com.punt-labs.lux"


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _luxd_exec_args() -> list[str]:
    """Return the command to invoke luxd.

    Resolution order:

    1. ``~/.local/bin/luxd`` (uv tool install symlink) -- resolved to absolute.
    2. Refuse to register -- raise ``RuntimeError`` instead of silently using
       ``sys.executable`` or ``shutil.which()``, either of which may resolve
       to a dev venv binary.
    """
    local_bin = Path.home() / ".local" / "bin" / "luxd"
    if local_bin.exists():
        # Use the symlink path, not resolve() — the symlink is the stable
        # contract that survives uv tool upgrade.
        logger.info("Service binary: %s (uv tool)", local_bin)
        return [str(local_bin), "--port", str(DEFAULT_HUB_PORT)]

    msg = (
        "Cannot find luxd binary at ~/.local/bin/luxd. "
        "Install lux first: uv tool install punt-lux"
    )
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# macOS -- launchd
# ---------------------------------------------------------------------------

_LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"
_LAUNCHD_PLIST = _LAUNCHD_DIR / f"{_LABEL}.plist"


def _launchd_plist_content() -> str:
    """Generate the launchd plist XML for luxd."""
    args = _luxd_exec_args()
    program_args = "\n".join(f"        <string>{_xml_escape(a)}</string>" for a in args)
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


def _launchd_install() -> None:
    """Write the plist and load luxd into launchd."""
    from punt_lux.paths import hub_log_dir

    hub_log_dir().mkdir(parents=True, exist_ok=True)
    _LAUNCHD_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Unload any existing service first -- handles upgrades where the
    # old plist pointed to a different binary.
    if _launchd_status():
        result = subprocess.run(
            ["launchctl", "unload", "-w", str(_LAUNCHD_PLIST)],
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

    content = _launchd_plist_content()
    tmp_path = _LAUNCHD_PLIST.with_name(_LAUNCHD_PLIST.name + ".tmp")
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
        tmp_path.replace(_LAUNCHD_PLIST)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("Wrote %s", _LAUNCHD_PLIST)

    subprocess.run(
        ["launchctl", "load", "-w", str(_LAUNCHD_PLIST)],
        check=True,
    )
    logger.info("Loaded %s into launchd", _LABEL)


def _launchd_uninstall() -> None:
    """Unload luxd from launchd and remove the plist."""
    if _LAUNCHD_PLIST.exists():
        result = subprocess.run(
            ["launchctl", "unload", "-w", str(_LAUNCHD_PLIST)],
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
        _LAUNCHD_PLIST.unlink()
        logger.info("Removed %s", _LAUNCHD_PLIST)
    else:
        logger.info("No plist found at %s -- nothing to uninstall", _LAUNCHD_PLIST)


def _launchd_status() -> bool:
    """Return whether the luxd launchd service is loaded."""
    result = subprocess.run(
        ["launchctl", "list", _LABEL],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Linux -- systemd user unit
# ---------------------------------------------------------------------------

_SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
_SYSTEMD_UNIT = _SYSTEMD_DIR / "lux.service"


def _systemd_escape(arg: str) -> str:
    """Escape a single argument for use in systemd unit ExecStart.

    systemd uses its own parser, not POSIX shell. Double-quote the value
    and backslash-escape embedded double-quotes and backslashes.
    """
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _systemd_unit_content() -> str:
    """Generate the systemd unit file content for luxd."""
    args = _luxd_exec_args()
    exec_start = " ".join(_systemd_escape(a) for a in args)
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


def _systemd_install() -> None:
    """Write the unit file, reload systemd, and enable+start luxd."""
    _SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    content = _systemd_unit_content()
    tmp_path = _SYSTEMD_UNIT.with_name(_SYSTEMD_UNIT.name + ".tmp")
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
        tmp_path.replace(_SYSTEMD_UNIT)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("Wrote %s", _SYSTEMD_UNIT)

    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        check=True,
    )
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", "lux"],
        check=True,
    )
    # Force restart to pick up new unit file.
    subprocess.run(
        ["systemctl", "--user", "restart", "lux"],
        check=True,
    )
    logger.info("Enabled and restarted lux.service")


def _systemd_uninstall() -> None:
    """Stop, disable, and remove the systemd unit."""
    if _SYSTEMD_UNIT.exists():
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "lux"],
            check=False,
        )
        _SYSTEMD_UNIT.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
        )
        logger.info("Removed %s", _SYSTEMD_UNIT)
    else:
        logger.info("No unit found at %s -- nothing to uninstall", _SYSTEMD_UNIT)


def _systemd_status() -> bool:
    """Return whether the luxd systemd user service is active."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "lux"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "active"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_platform() -> str:
    """Return ``'macos'`` or ``'linux'``. Raises on unsupported platforms."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    msg = f"Unsupported platform: {system}. lux hub-install supports macOS and Linux."
    raise SystemExit(msg)


def install() -> str:
    """Install luxd as a system service. Returns a status message."""
    plat = detect_platform()
    args = _luxd_exec_args()

    if plat == "macos":
        _launchd_install()
        running = _launchd_status()
    else:
        _systemd_install()
        running = _systemd_status()

    exec_display = " ".join(args)
    status_label = "running" if running else "installed (not yet running)"
    lines = [
        f"luxd {status_label} on port {DEFAULT_HUB_PORT}.",
        f"  Service: {_LAUNCHD_PLIST if plat == 'macos' else _SYSTEMD_UNIT}",
        f"  Command: {exec_display}",
    ]
    if plat == "linux" and not _has_linger():
        lines.append(
            "  Warning: loginctl linger is not enabled. "
            "The daemon will stop when you log out. "
            "Run: loginctl enable-linger"
        )
    return os.linesep.join(lines)


def uninstall() -> str:
    """Remove luxd system service. Returns a status message."""
    plat = detect_platform()
    if plat == "macos":
        _launchd_uninstall()
        path = _LAUNCHD_PLIST
    else:
        _systemd_uninstall()
        path = _SYSTEMD_UNIT
    return f"luxd uninstalled. Removed {path}."


def _has_linger() -> bool:
    """Check if loginctl linger is enabled for the current user (Linux only)."""
    try:
        user = os.getlogin()
    except OSError:
        return True  # Can't check; don't warn
    result = subprocess.run(
        ["loginctl", "show-user", user, "--property=Linger"],
        capture_output=True,
        text=True,
    )
    return "Linger=yes" in result.stdout
