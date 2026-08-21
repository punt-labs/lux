"""Admin verbs for ``lux display`` — install/uninstall/start/stop/status.

Parallels ``lux hub install|uninstall|start|stop|status`` from the hub group.
These live in their own module so ``cli/display.py`` (which owns the fused
theme/mode/window verbs) stays focused on runtime display operations rather
than launchd/systemd supervision.
"""

from __future__ import annotations

from pathlib import Path

import typer

from punt_lux.cli.display import display_app
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
    """Start the display through its supervisor if it is installed and stopped."""
    try:
        typer.echo(ServiceManager.for_display().start())
    except (ServiceNotInstalledError, ServiceActionFailedError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@display_app.command("stop")
def stop() -> None:
    """Stop the display through its supervisor; the service registration stays."""
    try:
        typer.echo(ServiceManager.for_display().stop())
    except ServiceActionFailedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@display_app.command("status")
def status(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Report display service state and current window process."""
    mgr = ServiceManager.for_display()
    typer.echo(
        f"Service: {'active' if mgr.is_active else 'inactive'} "
        f"({mgr.spec.launchd_label})"
    )
    dp = DisplayPaths(Path(socket) if socket else None)
    if dp.is_running():
        try:
            pid = int(dp.pid_path.read_text().strip())
            typer.echo(f"Display running (pid {pid}) at {dp.socket_path}")
        except (OSError, ValueError):
            typer.echo(f"Display running at {dp.socket_path} (pid unknown)")
    else:
        typer.echo(f"Display not running at {dp.socket_path}")
        raise typer.Exit(code=1)
