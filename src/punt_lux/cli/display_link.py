"""``lux display link`` -- the Hub's observed display-link state.

Registered onto :data:`punt_lux.cli.display.display_app` from its own module,
mirroring :mod:`punt_lux.cli.display_service` -- the render/fetch logic for
this one verb stays out of ``cli/display.py``'s per-command footprint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.cli._shared import (
    JsonFlag,
    OutputFlags,
    QuietFlag,
    VerboseFlag,
    connect_client,
    identity_from_flags,
    run,
)
from punt_lux.cli.display import display_app
from punt_lux.commands import CommandResult, Ctx
from punt_lux.commands._faults import render_error
from punt_lux.operations import OpError
from punt_lux.operations.models.display_link import ConnectedLinkState

if TYPE_CHECKING:
    from punt_lux.client._display_link_ops import DisplayLinkOps
    from punt_lux.operations.models.display_link import DisplayLinkState

__all__: list[str] = []


@final
class _LinkResult:
    """Render the display-link CLI result: readable text, or the OpError envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def text(state: DisplayLinkState) -> str:
        """Render either link shape readably: linkage, plus a retry delay when held."""
        if isinstance(state, ConnectedLinkState):
            return f"display:link:{state.linkage}"
        delay = state.retry_delay_seconds
        return f"display:link:{state.linkage} retry_delay={delay:.1f}s"

    @staticmethod
    async def fetch(ctx: Ctx[DisplayLinkOps]) -> CommandResult:
        """Fetch the link state and render it, or the transport's ``OpError``."""
        result = ctx.ops.get_link()
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=_LinkResult.text(result), json_data=result.model_dump(mode="json")
        )


@display_app.command("link")
def link(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the Hub's observed display-link state -- never proxies to the display."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[DisplayLinkOps] = Ctx(
        ops=connect_client(identity=identity), identity=identity
    )
    run(_LinkResult.fetch(ctx), flags)
