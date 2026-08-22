"""``lux beads`` — display the repository's one beads board (no LLM needed).

Not part of the ratified noun-grouped vocabulary (docs/architecture/target/
target.md's ten nouns): beads-board assembly is app-specific composition, not
a primitive engine operation. A bespoke, top-level convenience a human runs
from a shell, distinct from both `lux scene table` (the primitive it
composes) and the `lux-beads` applet (the live, session-bound sibling --
this command renders once and exits, with no menu registration or watch).

Formerly `lux show beads`, under a `show` Typer group with one command. The
ratified vocabulary has no top-level `show` noun (PL-PP-1: no shims for a
retired shape), so this moved to a bare top-level verb, unchanged otherwise.
"""

from __future__ import annotations

from typing import Self, final

import typer

from punt_lux.applets.board_ops import BoardOps, ScopedBoardOps
from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure
from punt_lux.client.facade import LuxClient
from punt_lux.operations import OpError, RenderRequest, RenderTableRequest
from punt_lux.operations.models.scene_results import SceneShown
from punt_lux.rest_transport import HubUnavailableError

__all__ = ["beads"]


@final
class BeadsBoardCommand:
    """The ``lux beads`` command: load the board, build its request, name it."""

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
        result = self._browser.load(all_issues=all_issues).result
        board = BeadsBoard.for_repo()
        note = (
            f"bd error: {result.reason}"
            if isinstance(result, BeadsFailure)
            else f"{len(result)} issues"
        )
        return board.request(result), note

    def push(
        self, client: BoardOps, request: RenderTableRequest | RenderRequest
    ) -> SceneShown | OpError:
        """Install the board through the route its request calls for.

        A table goes through the table route so the Hub *constructs* its live
        chrome — search, combos, the selection-bound detail panel; a message is a
        plain scene with no handlers to lose.
        """
        if isinstance(request, RenderTableRequest):
            return client.render_table(request)
        return client.render(request)


def beads(
    all_issues: bool = typer.Option(False, "--all", "-a", help="Include closed issues"),
) -> None:
    """Display the beads issue board — the repository's one board."""
    command = BeadsBoardCommand()
    request, note = command.request(all_issues=all_issues)
    try:
        client = ScopedBoardOps.for_client(LuxClient.connect())
        result = command.push(client, request)
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    if isinstance(result, OpError):
        typer.echo(f"Beads board not shown: {result.reason}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Beads board displayed ({note}).")
