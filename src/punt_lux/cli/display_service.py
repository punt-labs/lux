"""Admin verbs for ``lux display`` (install/uninstall/start/stop/restart/status)."""

from __future__ import annotations

from pathlib import Path

import typer

from punt_lux.cli.display import display_app
from punt_lux.display_restart import DisplayRestart, DisplayRestartError
from punt_lux.paths import DisplayPaths
from punt_lux.service import (
    ServiceActionFailedError,
    ServiceManager,
    ServiceNotInstalledError,
)

__all__ = ["display_app"]


@display_app.command("install")
def install() -> None:
    """Register the display window as a system service (launchd/systemd)."""
    typer.echo(ServiceManager.for_display().install())


@display_app.command("uninstall")
def uninstall() -> None:
    """Remove the display system service registration."""
    typer.echo(ServiceManager.for_display().uninstall())


@display_app.command("start")
def start() -> None:
    """Start the display; report status if already running."""
    if line := DisplayPaths().running_status_line():
        typer.echo(line)
        return
    try:
        typer.echo(ServiceManager.for_display().start())
    except (ServiceNotInstalledError, ServiceActionFailedError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@display_app.command("stop")
def stop() -> None:
    """Stop the display; the service registration stays."""
    try:
        typer.echo(ServiceManager.for_display().stop())
    except ServiceActionFailedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@display_app.command("restart")
def restart() -> None:
    """Restart the display through its service supervisor."""
    try:
        typer.echo(DisplayRestart().run())
    except DisplayRestartError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@display_app.command("doctor")
def doctor(
    *,
    fix: bool = typer.Option(
        False, "--fix", help="Repair legacy registrations and re-verify the port."
    ),
) -> None:
    """Diagnose (or repair, with --fix) legacy registrations and port conflicts."""
    mgr = ServiceManager.for_display()
    if fix:
        typer.echo("Repairing...")
        result = mgr.doctor_fix()
    else:
        result = mgr.doctor()
    typer.echo(result.render())
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


@display_app.command("status")
def status(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Report display service state and current window process."""
    mgr = ServiceManager.for_display()
    state = "active" if mgr.is_active else "inactive"
    typer.echo(f"Service: {state} ({mgr.spec.launchd_label})")
    dp = DisplayPaths(Path(socket) if socket else None)
    if line := dp.running_status_line():
        typer.echo(line)
        return
    typer.echo(f"Display not running at {dp.socket_path}")
    raise typer.Exit(code=1)
