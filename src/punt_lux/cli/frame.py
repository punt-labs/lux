"""``lux frame`` — change a frame's transient minimize state.

The design vocabulary (docs/architecture/client-surface-parity-design.md
§Frame) describes a future four-verb split (``raise|lower|close|expire``)
backed by a richer state model; the shipped ``FrameStatePatch`` (.3) only
carries ``minimized: bool | None``, so this verb ships as the one the data
model actually supports today -- ``lux frame set-state <id> --minimized``.
The four-verb split is `.5`'s scope once the richer patch model exists.
"""

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
from punt_lux.commands import Ctx, FrameOps, frame_set_state
from punt_lux.operations import FrameStatePatch, OpError

frame_app = typer.Typer(
    name="frame",
    help="Change a frame's transient minimize state.",
    no_args_is_help=True,
)

__all__ = ["frame_app"]


@frame_app.command("set-state")
def set_state(
    frame_id: Annotated[str, typer.Argument(help="Frame id to update.")],
    minimized: Annotated[
        bool | None,
        typer.Option(
            "--minimized/--no-minimized",
            help="Minimize or restore the frame. Omit to leave state unchanged.",
        ),
    ] = None,
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
    """Change a frame's minimize state."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    patch = FrameStatePatch.parse({"minimized": minimized})
    if isinstance(patch, OpError):
        typer.echo(f"error: {patch.reason}", err=True)
        raise typer.Exit(code=1)
    ctx: Ctx[FrameOps] = Ctx(ops=connect_client(), identity=identity)
    run(frame_set_state(ctx, frame_id, patch), flags)
