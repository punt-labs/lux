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
def display(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Start the Lux display server."""
    from punt_lux.display import DisplayServer

    server = DisplayServer(socket)
    server.run()


if __name__ == "__main__":
    app()
