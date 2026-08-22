"""``lux event`` — recent events emitted by/for the caller (caller-scoped)."""

from __future__ import annotations

from typing import Annotated

import typer

from punt_lux.cli._shared import (
    JsonFlag,
    OutputFlags,
    QuietFlag,
    VerboseFlag,
    connect_client,
    identity_from_flags,
    run,
)
from punt_lux.commands import Ctx, EventOps, event_ls

event_app = typer.Typer(
    name="event",
    help="Recent events emitted by/for the caller.",
    no_args_is_help=True,
)

__all__ = ["event_app"]


@event_app.command("ls")
def ls(
    count: Annotated[
        int, typer.Option("--count", min=0, max=200, help="Max events to return.")
    ] = 50,
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the display's recent interactions."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[EventOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(event_ls(ctx, count), flags)
