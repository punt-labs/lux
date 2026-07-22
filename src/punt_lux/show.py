"""CLI subcommands for ``lux show`` — pre-built display scenes.

Each command reads local data, builds an element tree, and sends it to luxd over
its REST API through :class:`LuxRestClient`. No display socket, no MCP round-trip,
no LLM in the loop — the CLI is a thin REST client of the one engine, and luxd
decides whether the display is reachable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

import typer

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.operations import OpError, RenderRequest
from punt_lux.operations.models.render import FrameSpec
from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_transport import HubUnavailableError

show_app = typer.Typer(
    help="Show pre-built scenes in the Lux display.",
    no_args_is_help=True,
)

__all__ = ["show_app"]


@final
class BeadsBoard:
    """The beads issue board: load it, build its scene, name its outcome."""

    _browser: BeadsBrowser
    __slots__ = ("_browser",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._browser = BeadsBrowser()
        return self

    def request(self, *, all_issues: bool) -> tuple[RenderRequest, str]:
        """Build the scene render request and a note describing what it carries.

        A bd failure still yields a request — the board renders a visible error
        element — so the note distinguishes that case from a real issue count.
        """
        issues, load_error = self._browser.load(all_issues=all_issues)
        elements = self._browser.build_elements((issues, load_error))
        project = Path.cwd().name or "unknown"
        note = f"bd error: {load_error}" if load_error else f"{len(issues)} issues"
        request = RenderRequest(
            scene_id=f"beads-{project}",
            elements=[e.to_dict() for e in elements],
            title=f"Beads: {project}",
            frame=FrameSpec(
                frame_id=f"beads-{project}", frame_title=f"Beads: {project}"
            ),
        )
        return request, note


@show_app.command("beads")
def beads(
    all_issues: bool = typer.Option(False, "--all", "-a", help="Include closed issues"),
) -> None:
    """Display the beads issue board in the Lux window."""
    request, note = BeadsBoard().request(all_issues=all_issues)
    try:
        client = LuxRestClient.connect()
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    result = client.render(request)
    if isinstance(result, OpError):
        typer.echo(f"Beads board not shown: {result.reason}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Beads board displayed ({note}).")
