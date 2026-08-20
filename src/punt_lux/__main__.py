"""CLI entry point for lux."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

import typer

from punt_lux import __version__
from punt_lux.doctor_report import FAIL, OK, OPTIONAL, DoctorReport
from punt_lux.log_level import level_from_env
from punt_lux.show import show_app


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

_PLUGIN_ID = "lux@punt-labs"


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
    from pathlib import Path

    from punt_lux.paths import DisplayPaths

    try:
        from punt_lux.display import RenderLoop
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

    logging.basicConfig(
        filename=str(log_path),
        level=level_from_env("INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    server = RenderLoop(socket, test_auto_click=test_auto_click)
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
    Routes through the shared ``ping`` command singleton and prints its rendered
    line directly — the same three-way status ("not running" / "timeout" /
    "error: <reason>") the MCP tool and REST route report, on one code path.
    """
    import asyncio

    from punt_lux.cli_identity import CliIdentity
    from punt_lux.commands import Ctx as CommandCtx, PingOps, ping as ping_command
    from punt_lux.domain.hub.display_link import DEFAULT_RECV_TIMEOUT
    from punt_lux.rest_client import LuxRestClient
    from punt_lux.rest_transport import HubUnavailableError

    display_wait = timeout if timeout is not None else DEFAULT_RECV_TIMEOUT
    http_timeout = display_wait + _PING_HTTP_MARGIN_SECONDS

    try:
        client = LuxRestClient.connect(timeout=http_timeout)
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None

    ctx: CommandCtx[PingOps] = CommandCtx(ops=client, identity=CliIdentity.resolve())
    result = asyncio.run(ping_command(ctx, timeout))

    if result.error:
        typer.echo(result.text, err=True)
        raise typer.Exit(code=result.exit_code)

    typer.echo(result.text)


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


@app.command()
def doctor(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Check installation health."""
    from pathlib import Path

    from punt_lux.doctor_checks import EnvironmentChecks
    from punt_lux.paths import DisplayPaths

    _check = DoctorReport()

    # Python version
    v = sys.version_info
    if v >= (3, 13):
        _check(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _check(
            FAIL,
            f"Python {v.major}.{v.minor}.{v.micro} (requires 3.13+)",
        )

    # imgui-bundle (part of display extras)
    try:
        from imgui_bundle import (
            imgui,  # noqa: F401  # pyright: ignore[reportUnusedImport]
        )

        _check(OK, "imgui-bundle installed")
    except ImportError:
        _check(
            OPTIONAL,
            "imgui-bundle not installed (run: pip install 'punt-lux[display]')",
            required=False,
        )

    # Fonts and the plugin are the machine's business, not lux's — advisory
    # either way, so a missing one never fails the run.
    checks = EnvironmentChecks(_check, _PLUGIN_ID)
    checks.fonts()

    # Display server
    dp = DisplayPaths(Path(socket) if socket else None)
    path = dp.socket_path
    if dp.is_running():
        _check(OK, f"Display server running at {path}")
    else:
        _check(OPTIONAL, f"Display server not running at {path}", required=False)

    checks.plugin()

    print(_check.render())
    if _check.failed > 0:
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
    """Restart luxd through the service manager, reporting what came back."""
    from punt_lux.hub_restart import HubRestart, HubRestartError

    print("Restarting luxd...")
    try:
        print(HubRestart().run())
    except HubRestartError as exc:
        print(str(exc))
        raise typer.Exit(code=1) from None


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
