"""``lux hub`` — admin subcommands for luxd process supervision.

The admin tier of the design vocabulary: install/uninstall the launchd or
systemd service, report status, restart. These verbs never leave the CLI —
they are absent from MCP and REST by construction (no superuser surface).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import typer

from punt_lux.hub_paths import HubPaths
from punt_lux.hub_restart import HubRestart, HubRestartError
from punt_lux.service import ServiceManager

hub_app = typer.Typer(
    name="hub",
    help="Admin: manage the luxd process supervisor service.",
    no_args_is_help=True,
)

__all__ = ["hub_app"]


@hub_app.command("install")
def install() -> None:
    """Register luxd as a system service (launchd on macOS, systemd on Linux)."""
    typer.echo(ServiceManager().install())


@hub_app.command("uninstall")
def uninstall() -> None:
    """Remove the luxd system service registration."""
    typer.echo(ServiceManager().uninstall())


@hub_app.command("start")
def start() -> None:
    """Report luxd status; luxd is auto-started by its supervisor after install."""
    hub_paths = HubPaths()
    if not hub_paths.is_running():
        typer.echo("luxd not running. Run 'lux hub install' to register the service.")
        raise typer.Exit(code=1)
    port = hub_paths.read_port()
    label = f"luxd running (port {port})" if port is not None else "luxd running"
    typer.echo(label)


@hub_app.command("stop")
def stop() -> None:
    """Stop luxd, leaving the service registration in place."""
    typer.echo(ServiceManager().stop())


@hub_app.command("restart")
def restart() -> None:
    """Restart luxd through the service supervisor."""
    typer.echo("Restarting luxd...")
    try:
        typer.echo(HubRestart().run())
    except HubRestartError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@hub_app.command("status")
def status() -> None:
    """Show luxd hub status including port and active session count."""
    hub_paths = HubPaths()
    if not hub_paths.is_running():
        typer.echo("luxd not running")
        raise typer.Exit(code=1)

    try:
        pid = int(hub_paths.pid_path.read_text().strip())
    except (ValueError, OSError):
        pid = None

    port = hub_paths.read_port()
    if port is None:
        typer.echo(f"luxd running (pid {pid}) but port file unreadable")
        raise typer.Exit(code=1)

    request = urllib.request.Request(f"http://127.0.0.1:{port}/health")
    try:
        with urllib.request.urlopen(request, timeout=2) as resp:  # noqa: S310
            data = json.loads(resp.read())
        sessions = data.get("sessions", 0)
        typer.echo(f"luxd running (pid {pid}, port {port})")
        typer.echo(f"  sessions: {sessions}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        typer.echo(
            f"luxd running (pid {pid}, port {port}) but health check failed: {exc}"
        )
