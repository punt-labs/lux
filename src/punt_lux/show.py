"""CLI subcommands for ``lux show`` — pre-built display scenes.

Each command reads local data, builds a request, and sends it to luxd through
:class:`LuxRestClient`: the CLI is a thin REST client of the one engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

import typer

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure
from punt_lux.operations import OpError, RenderRequest, RenderTableRequest
from punt_lux.operations.models.scene_results import SceneShown
from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_transport import HubUnavailableError

show_app = typer.Typer(
    help="Show pre-built scenes in the Lux display.",
    no_args_is_help=True,
)

__all__ = ["show_app"]


@final
class BeadsBoardCommand:
    """The ``lux show beads`` command: load the board, build its request, name it."""

    _browser: BeadsBrowser
    __slots__ = ("_browser",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._browser = BeadsBrowser()
        return self

    def request(
        self, *, all_issues: bool
    ) -> tuple[RenderTableRequest | RenderRequest, str]:
        """Build the board's request and a note describing what it will show.

        The board is the repository's one board, so this command refreshes the same
        scene a session's menu entry does rather than opening a second copy. The
        note distinguishes a bd failure from a real issue count.
        """
        result = self._browser.load(all_issues=all_issues)
        board = BeadsBoard.for_project(Path.cwd().name or "unknown")
        note = (
            f"bd error: {result.reason}"
            if isinstance(result, BeadsFailure)
            else f"{len(result)} issues"
        )
        return board.request(result), note

    def push(
        self, client: LuxRestClient, request: RenderTableRequest | RenderRequest
    ) -> SceneShown | OpError:
        """Install the board through the route its request calls for.

        A table goes through the table route so the Hub *constructs* its live
        chrome — search, combos, the selection-bound detail panel; a message is a
        plain scene with no handlers to lose.
        """
        if isinstance(request, RenderTableRequest):
            return client.render_table(request)
        return client.render(request)


@show_app.command("beads")
def beads(
    all_issues: bool = typer.Option(False, "--all", "-a", help="Include closed issues"),
) -> None:
    """Display the beads issue board — the repository's one board."""
    command = BeadsBoardCommand()
    request, note = command.request(all_issues=all_issues)
    try:
        result = command.push(LuxRestClient.connect(), request)
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    if isinstance(result, OpError):
        typer.echo(f"Beads board not shown: {result.reason}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Beads board displayed ({note}).")
