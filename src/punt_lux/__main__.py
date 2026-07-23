"""CLI entry point for lux."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import Protocol

import typer

from punt_lux import __version__
from punt_lux.show import show_app

_LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _version_callback(value: bool) -> None:
    if value:
        print(f"lux {__version__}")
        raise typer.Exit


app = typer.Typer(
    name="lux",
    help="lux: visual output surface for AI agents.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def _main(  # pyright: ignore[reportUnusedFunction]
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """lux: visual output surface for AI agents."""


hook_app = typer.Typer(hidden=True)
app.add_typer(hook_app, name="hook")
app.add_typer(show_app, name="show")

# Symbols for doctor output

_OK = "\u2713"  # ✓
_FAIL = "\u2717"  # ✗
_OPTIONAL = "\u2014"  # —

_PLUGIN_ID = "lux@punt-labs"


class _CheckFn(Protocol):
    def __call__(self, symbol: str, message: str, *, required: bool = True) -> None: ...


# Product commands


@app.command()
def display(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    test_auto_click: bool = typer.Option(
        False,
        "--test-auto-click",
        help="Auto-fire click events for buttons (testing)",
    ),
) -> None:
    """Start the Lux display server."""
    import logging
    from pathlib import Path

    from punt_lux.paths import DisplayPaths

    try:
        from punt_lux.display import DisplayServer
    except ModuleNotFoundError as exc:
        _display_modules = {"imgui_bundle", "numpy", "PIL", "OpenGL"}
        if exc.name and exc.name.split(".")[0] in _display_modules:
            typer.echo(
                "Display extras not installed. Run: pip install 'punt-lux[display]'",
                err=True,
            )
            raise typer.Exit(code=1) from None
        raise

    dp = DisplayPaths(Path(socket) if socket else None)
    log_path = dp.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    import os

    raw_level = os.environ.get("LUX_LOG_LEVEL", "INFO").upper()
    log_level = _LOG_LEVELS.get(raw_level)
    if log_level is None:
        import sys

        print(
            f"WARNING: LUX_LOG_LEVEL={raw_level!r} is not valid, defaulting to INFO",
            file=sys.stderr,
        )
        log_level = logging.INFO
    logging.basicConfig(
        filename=str(log_path),
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    server = DisplayServer(socket, test_auto_click=test_auto_click)
    server.run()


@app.command()
def enable() -> None:
    """Enable visual output for this project."""
    from punt_lux.config import ConfigManager

    ConfigManager().write_field("display", "y")
    print("Lux display enabled.")


@app.command()
def disable() -> None:
    """Disable visual output for this project."""
    from punt_lux.config import ConfigManager

    ConfigManager().write_field("display", "n")
    print("Lux display disabled.")


# Hook dispatcher (internal)


@hook_app.command("session-start")
def cc_session_start() -> None:
    """SessionStart — internal hook dispatcher."""
    from punt_lux.hooks import emit, handle_session_start

    # Skip stdin — this handler needs no payload and the pipe may never close.
    result = handle_session_start()
    emit(result)


@hook_app.command("post-bash")
def cc_post_bash() -> None:
    """PostToolUse Bash — internal hook dispatcher."""
    from punt_lux.hooks import handle_post_bash, read_hook_input

    data = read_hook_input()
    handle_post_bash(data)


# Admin commands


@app.command()
def version() -> None:
    """Print the version."""
    from punt_lux import __version__

    print(f"lux {__version__}")


_PING_HTTP_MARGIN_SECONDS = 2.0  # HTTP bound sits a margin above the display leg


@app.command()
def ping(
    # None derives the wait from the display budget; bounds match the route so
    # an out-of-range value is a clear typer error (clamp defaults off), not HTTP.
    timeout: float | None = typer.Option(
        None, "--timeout", "-t", min=0.1, max=30, help="Seconds to wait for the ping."
    ),
) -> None:
    """Ping the display through luxd and print round-trip time.

    ``--timeout`` (0.1-30s) is the real display-leg budget over luxd's REST API;
    the HTTP round-trip sits a margin above it, so a slow display reports "timeout".
    """
    from punt_lux.display_client import DEFAULT_RECV_TIMEOUT
    from punt_lux.operations import OpError
    from punt_lux.rest_client import LuxRestClient
    from punt_lux.rest_transport import HubUnavailableError

    display_wait = timeout if timeout is not None else DEFAULT_RECV_TIMEOUT
    http_timeout = display_wait + _PING_HTTP_MARGIN_SECONDS

    try:
        result = LuxRestClient.connect(timeout=http_timeout).ping(timeout)
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None

    if isinstance(result, OpError):
        down = result.code == "display_unavailable"
        typer.echo("Display not running" if down else "timeout", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"pong rtt={result.rtt_seconds:.3f}s")


@app.command()
def status(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Check whether the display server is running."""
    from pathlib import Path

    from punt_lux.paths import DisplayPaths

    dp = DisplayPaths(Path(socket) if socket else None)
    path = dp.socket_path
    running = dp.is_running()

    if running:
        try:
            pid = int(dp.pid_path.read_text().strip())
            print(f"Display running (pid {pid}) at {path}")
        except (OSError, ValueError):
            print(f"Display running at {path} (pid unknown)")
    else:
        print(f"Display not running at {path}")

    raise typer.Exit(code=0 if running else 1)


def _check_fonts(_check: _CheckFn) -> None:
    """Check for system fonts used by the display server."""
    import platform
    from pathlib import Path

    def _first_existing(*candidates: str) -> str | None:
        for p in candidates:
            if Path(p).is_file():
                return p
        return None

    if platform.system() == "Darwin":
        primary = _first_existing(
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        )
        sym = _first_existing("/System/Library/Fonts/Apple Symbols.ttf")
        math = _first_existing(
            "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
            "/Library/Fonts/STIXTwoMath.otf",
        )
        hint = ""  # macOS always has these
        math_hint = ""  # ships with macOS
    else:
        primary = _first_existing(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        )
        sym = _first_existing(
            "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
            "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
        )
        math = _first_existing(
            "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
            "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
        )
        hint = " \u2014 apt install fonts-dejavu-core or fonts-noto"
        math_hint = " \u2014 apt install fonts-noto"

    if primary:
        _check(_OK, f"Font: {primary}", required=False)
    else:
        msg = f"No Unicode font found{hint} (falls back to Latin-only)"
        _check(_FAIL, msg, required=False)

    if sym:
        _check(_OK, f"Symbol font: {sym}", required=False)
    else:
        _check(
            _OPTIONAL,
            "No symbol font found (math symbols may not render)",
            required=False,
        )

    if math:
        _check(_OK, f"Math font: {math}", required=False)
    else:
        _check(
            _OPTIONAL,
            f"No math font found{math_hint}"
            " (Z notation double-struck letters may not render)",
            required=False,
        )


def _check_plugin(
    _check: _CheckFn,
) -> None:
    """Check Claude CLI and plugin registration (optional)."""
    claude = shutil.which("claude")
    if claude:
        _check(_OK, f"claude CLI: {claude}", required=False)
    else:
        _check(_OPTIONAL, "claude CLI not found (needed for plugin)", required=False)
        return

    result = subprocess.run(  # noqa: S603
        [claude, "plugin", "list"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if _PLUGIN_ID in result.stdout:
        _check(_OK, f"Plugin: {_PLUGIN_ID}", required=False)
    else:
        _check(
            _OPTIONAL,
            "Plugin not installed (run 'lux install')",
            required=False,
        )


@app.command()
def doctor(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Check installation health."""
    from pathlib import Path

    from punt_lux.paths import DisplayPaths

    passed = 0
    failed = 0
    lines: list[str] = []

    def _check(symbol: str, message: str, *, required: bool = True) -> None:
        nonlocal passed, failed
        lines.append(f"{symbol} {message}")
        if symbol == _OK:
            passed += 1
        elif symbol == _FAIL and required:
            failed += 1

    # Python version
    v = sys.version_info
    if v >= (3, 13):
        _check(_OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _check(
            _FAIL,
            f"Python {v.major}.{v.minor}.{v.micro} (requires 3.13+)",
        )

    # imgui-bundle (part of display extras)
    try:
        from imgui_bundle import (
            imgui,  # noqa: F401  # pyright: ignore[reportUnusedImport]
        )

        _check(_OK, "imgui-bundle installed")
    except ImportError:
        _check(
            _OPTIONAL,
            "imgui-bundle not installed (run: pip install 'punt-lux[display]')",
            required=False,
        )

    # Fonts (not required — falls back to ImGui default, but Unicode won't render)
    _check_fonts(_check)

    # Display server
    dp = DisplayPaths(Path(socket) if socket else None)
    path = dp.socket_path
    if dp.is_running():
        _check(_OK, f"Display server running at {path}")
    else:
        _check(_OPTIONAL, f"Display server not running at {path}", required=False)

    # Claude CLI + plugin registration (optional)
    _check_plugin(_check)

    print("=" * 40)
    for line in lines:
        print(line)
    print("=" * 40)
    print(f"{passed} passed, {failed} failed")

    if failed > 0:
        raise typer.Exit(code=1)


@app.command("hub-install")
def hub_install() -> None:
    """Register luxd as a system service (launchd/systemd)."""
    from punt_lux.service import ServiceManager

    print(ServiceManager().install())


@app.command("hub-uninstall")
def hub_uninstall() -> None:
    """Remove luxd system service."""
    from punt_lux.service import ServiceManager

    print(ServiceManager().uninstall())


def _restart_hub() -> None:
    """Send SIGTERM and wait for the service manager to respawn luxd."""
    import os as _os
    import signal
    import time

    from punt_lux.hub_paths import HubPaths

    hub_paths = HubPaths()
    pid_path = hub_paths.pid_path
    try:
        old_pid = int(pid_path.read_text().strip())
        _os.kill(old_pid, signal.SIGTERM)
        print(f"Sent SIGTERM to luxd (pid {old_pid}), waiting for restart...")
    except (ValueError, OSError) as exc:
        print(f"Could not signal luxd: {exc}")
        raise typer.Exit(code=1) from None

    # Wait for old process to die
    for _ in range(20):  # 10 seconds
        time.sleep(0.5)
        try:
            _os.kill(old_pid, 0)
        except ProcessLookupError:
            break  # Old process is gone
        except PermissionError:
            break  # Can't check, assume dead
    else:
        print(f"luxd (pid {old_pid}) did not stop within 10s")
        raise typer.Exit(code=1)

    # Wait for launchd/systemd to respawn with a new PID
    for _ in range(20):  # 10 seconds
        time.sleep(0.5)
        if not hub_paths.is_running():
            continue
        try:
            new_pid = int(pid_path.read_text().strip())
        except (ValueError, OSError):
            continue
        if new_pid == old_pid:
            continue
        port = hub_paths.read_port()
        if port is not None:
            print(f"luxd restarted (pid {new_pid}, port {port})")
        else:
            print(f"luxd restarted (pid {new_pid}, port file not yet written)")
        return
    print("luxd did not restart within 10s")
    raise typer.Exit(code=1)


@app.command("ensure-hub")
def ensure_hub(
    restart: bool = typer.Option(False, "--restart", help="Restart luxd if running"),
) -> None:
    """Ensure luxd is running. Restart if --restart flag is set."""
    from punt_lux.hub_paths import HubPaths

    hub_paths = HubPaths()
    if restart and hub_paths.is_running():
        _restart_hub()
        return

    if hub_paths.is_running():
        port = hub_paths.read_port()
        if port is not None:
            print(f"luxd running (port {port})")
        else:
            print("luxd running (port unknown)")
    else:
        print("luxd not running. Run 'lux hub-install' to register the service.")
        raise typer.Exit(code=1)


@app.command("hub-status")
def hub_status() -> None:
    """Show luxd hub status."""
    import json
    import urllib.request

    from punt_lux.hub_paths import HubPaths

    hub_paths = HubPaths()
    if not hub_paths.is_running():
        print("luxd not running")
        raise typer.Exit(code=1)

    try:
        pid = int(hub_paths.pid_path.read_text().strip())
    except (ValueError, OSError):
        pid = None

    port = hub_paths.read_port()
    if port is None:
        print(f"luxd running (pid {pid}) but port file unreadable")
        raise typer.Exit(code=1)

    # Try to hit the health endpoint
    try:
        url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
            data = json.loads(resp.read())
        sessions = data.get("sessions", 0)
        print(f"luxd running (pid {pid}, port {port})")
        print(f"  sessions: {sessions}")
    except Exception as exc:  # noqa: BLE001
        print(f"luxd running (pid {pid}, port {port}) but health check failed: {exc}")


@app.command()
def install() -> None:
    """Install the Claude Code plugin via the punt-labs marketplace."""
    claude = shutil.which("claude")
    if not claude:
        typer.echo("Error: claude CLI not found on PATH", err=True)
        raise typer.Exit(code=1)

    result = subprocess.run(  # noqa: S603
        [claude, "plugin", "install", _PLUGIN_ID, "--scope", "user"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("Error: plugin install failed", err=True)
        raise typer.Exit(code=1)
    print("Installed. Restart Claude Code to activate.")


@app.command()
def uninstall() -> None:
    """Uninstall the Claude Code plugin."""
    claude = shutil.which("claude")
    if not claude:
        typer.echo("Error: claude CLI not found on PATH", err=True)
        raise typer.Exit(code=1)

    result = subprocess.run(  # noqa: S603
        [claude, "plugin", "uninstall", _PLUGIN_ID, "--scope", "user"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("Error: plugin uninstall failed", err=True)
        raise typer.Exit(code=1)
    print("Uninstalled.")


if __name__ == "__main__":
    app()
