"""CLI subcommands for ``lux show`` — pre-built display scenes.

Each command reads local data, builds a scene payload, and sends it
to the display server via :class:`LuxClient`.  No MCP round-trip,
no LLM in the loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from punt_lux.apps.beads import build_beads_payload, load_beads

show_app = typer.Typer(
    help="Show pre-built scenes in the Lux display.",
    no_args_is_help=True,
)

# Re-export for backwards compatibility with any external callers.
__all__ = ["build_beads_payload", "load_beads", "show_app"]


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@show_app.command("beads")
def beads(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    all_issues: bool = typer.Option(False, "--all", "-a", help="Include closed issues"),
) -> None:
    """Display the beads issue board in the Lux window."""
    from punt_lux.client import LuxClient
    from punt_lux.paths import default_socket_path
    from punt_lux.protocol import element_from_dict

    beads_dir = Path(".beads")
    if not beads_dir.is_dir():
        typer.echo(
            "No .beads/ directory found. Run `bd init` to set up beads.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        issues = load_beads(beads_dir, all_issues=all_issues)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    project = Path.cwd().name or "unknown"
    sock_path = Path(socket) if socket else default_socket_path()

    if not issues:
        empty_text: dict[str, Any] = {
            "kind": "text",
            "id": "empty",
            "content": "No active issues.",
        }
        elements = [element_from_dict(empty_text)]
        with LuxClient(sock_path, name="lux-beads") as client:
            ack = client.show(
                f"beads-{project}",
                elements,
                title=f"Beads: {project}",
                frame_id=f"beads-{project}",
                frame_title=f"Beads: {project}",
            )
        if ack is None:
            typer.echo("Timeout: display server did not respond.", err=True)
            raise typer.Exit(code=1)
        typer.echo("No active issues.")
        raise typer.Exit(code=0)

    payload = build_beads_payload(issues)

    table: dict[str, Any] = {
        "kind": "table",
        "id": "table",
        "columns": payload["columns"],
        "rows": payload["rows"],
        "flags": ["borders", "row_bg", "resizable", "copy_id"],
        "filters": payload["filters"],
        "detail": payload["detail"],
    }

    elements = [element_from_dict(table)]

    with LuxClient(sock_path, name="lux-beads") as client:
        ack = client.show(
            f"beads-{project}",
            elements,
            title=f"Beads: {project}",
            frame_id=f"beads-{project}",
            frame_title=f"Beads: {project}",
        )

    if ack is None:
        typer.echo("Timeout: display server did not respond.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Beads board displayed ({len(issues)} issues).")
