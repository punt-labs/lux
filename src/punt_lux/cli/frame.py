"""``lux frame`` -- close a frame."""

from __future__ import annotations

from typing import Annotated

import typer

from punt_lux.cli._shared import (
    AgentFlag,
    AsFlag,
    JsonFlag,
    KindFlag,
    NameFlag,
    OutputFlags,
    QuietFlag,
    RepoFlag,
    VerboseFlag,
    connect_client,
    identity_from_flags,
    run,
)
from punt_lux.commands import Ctx, FrameOps, frame_close

frame_app = typer.Typer(name="frame", help="Close a frame.", no_args_is_help=True)

__all__ = ["frame_app"]


@frame_app.command("close")
def close(
    frame_id: Annotated[str, typer.Argument(help="Frame id to close.")],
    *,
    as_: AsFlag = None,
    kind: KindFlag = None,
    name: NameFlag = None,
    repo: RepoFlag = None,
    agent: AgentFlag = None,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Close a frame: tear down its scenes on the Hub."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    ctx: Ctx[FrameOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(frame_close(ctx, frame_id), flags)
