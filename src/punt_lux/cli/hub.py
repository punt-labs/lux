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
from punt_lux.service import (
    ServiceActionFailedError,
    ServiceManager,
    ServiceNotInstalledError,
)

hub_app = typer.Typer(
    name="hub",
    help="Admin: manage the luxd process supervisor service.",
    no_args_is_help=True,
)

__all__ = ["hub_app"]


@hub_app.command("install")
def install() -> None:
    """Register luxd as a system service (launchd on macOS, systemd on Linux)."""
    typer.echo(ServiceManager.for_hub().install())


@hub_app.command("uninstall")
def uninstall() -> None:
    """Remove the luxd system service registration."""
    typer.echo(ServiceManager.for_hub().uninstall())


@hub_app.command("start")
def start() -> None:
    """Start luxd if it is installed and stopped; report status if already running."""
    hub_paths = HubPaths()
    if hub_paths.is_running():
        port = hub_paths.read_port()
        label = f"luxd running (port {port})" if port is not None else "luxd running"
        typer.echo(label)
        return
    try:
        typer.echo(ServiceManager.for_hub().start())
    except (ServiceNotInstalledError, ServiceActionFailedError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@hub_app.command("stop")
def stop() -> None:
    """Stop luxd, leaving the service registration in place."""
    try:
        typer.echo(ServiceManager.for_hub().stop())
    except ServiceActionFailedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@hub_app.command("restart")
def restart() -> None:
    """Restart luxd through the service supervisor."""
    typer.echo("Restarting luxd...")
    try:
        typer.echo(HubRestart().run())
    except HubRestartError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@hub_app.command("doctor")
def doctor(
    *,
    fix: bool = typer.Option(
        False, "--fix", help="Repair legacy registrations and re-verify the port."
    ),
) -> None:
    """Diagnose (or repair, with --fix) legacy registrations and port conflicts."""
    mgr = ServiceManager.for_hub()
    if fix:
        typer.echo("Repairing...")
        result = mgr.doctor_fix()
    else:
        result = mgr.doctor()
    typer.echo(result.render())
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


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
