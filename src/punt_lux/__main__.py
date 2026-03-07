"""CLI entry point for lux."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="lux",
    help="The paintbrush for Claude. Visual output surface for AI agents.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Show the current version."""
    from punt_lux import __version__

    print(f"lux {__version__}")


@app.command()
def status(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Check whether the Lux display server is running."""
    from pathlib import Path

    from punt_lux.paths import default_socket_path, is_display_running, pid_file_path

    path = Path(socket) if socket else default_socket_path()
    running = is_display_running(path)

    if running:
        try:
            pid = int(pid_file_path(path).read_text().strip())
            print(f"Display running (pid {pid}) at {path}")
        except (OSError, ValueError):
            print(f"Display running at {path} (pid unknown)")
    else:
        print(f"Display not running at {path}")

    raise typer.Exit(code=0 if running else 1)


@app.command()
def display(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Start the Lux display server."""
    from punt_lux.display import DisplayServer

    server = DisplayServer(socket)
    server.run()


if __name__ == "__main__":
    app()
