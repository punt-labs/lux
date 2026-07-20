"""CLI subcommands for ``lux show`` — pre-built display scenes.

Each command reads local data, builds a scene payload, and sends it to the
display server via :class:`DisplayClient`. No MCP round-trip, no LLM in the loop.
"""

from __future__ import annotations

from pathlib import Path

import typer

from punt_lux.apps.beads import BeadsBrowser

show_app = typer.Typer(
    help="Show pre-built scenes in the Lux display.",
    no_args_is_help=True,
)

__all__ = ["show_app"]


@show_app.command("beads")
def beads(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    all_issues: bool = typer.Option(False, "--all", "-a", help="Include closed issues"),
) -> None:
    """Display the beads issue board in the Lux window."""
    from punt_lux.display_client import DisplayClient
    from punt_lux.paths import DisplayPaths

    browser = BeadsBrowser()
    issues, load_error = browser.load(all_issues=all_issues)

    project = Path.cwd().name or "unknown"
    paths = DisplayPaths(Path(socket) if socket else None)
    # Down-check up front; the send is SO_SNDTIMEO-bounded, not ack-gated.
    if not paths.is_running():
        typer.echo("Display server is not running.", err=True)
        raise typer.Exit(code=1)
    elements = browser.build_elements((issues, load_error))

    with DisplayClient(paths.socket_path, name="lux-beads") as client:
        client.show(
            f"beads-{project}",
            elements,
            title=f"Beads: {project}",
            frame_id=f"beads-{project}",
            frame_title=f"Beads: {project}",
        )
    note = f"bd error: {load_error}" if load_error else f"{len(issues)} issues"
    typer.echo(f"Beads board displayed ({note}).")
