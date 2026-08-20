"""``lux error`` — recent errors for the caller (caller-scoped)."""

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
from punt_lux.commands import Ctx, ErrorOps, error_ls

error_app = typer.Typer(
    name="error",
    help="Recent errors for the caller.",
    no_args_is_help=True,
)

__all__ = ["error_app"]


@error_app.command("ls")
def ls(
    count: Annotated[
        int, typer.Option("--count", min=0, max=100, help="Max errors to return.")
    ] = 20,
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the display's recent errors."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[ErrorOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(error_ls(ctx, count), flags)
