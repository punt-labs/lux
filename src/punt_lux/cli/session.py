"""``lux session`` — list/inspect Hub sessions and declare caller identity."""

from __future__ import annotations

import asyncio
import json as _json
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
    scope_for,
)
from punt_lux.commands import Ctx, SessionOps, session_identify, session_ls

session_app = typer.Typer(
    name="session",
    help="List and inspect Hub sessions; declare caller identity.",
    no_args_is_help=True,
)

__all__ = ["session_app"]


@session_app.command("ls")
def ls(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """List every session the Hub is currently tracking (metadata only)."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[SessionOps] = Ctx(ops=connect_client(), identity=identity)
    run(session_ls(ctx), flags)


@session_app.command("inspect")
def inspect(
    connection_id: Annotated[
        str, typer.Argument(help="Connection id from `lux session ls`.")
    ],
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Show one session's metadata by connection id."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[SessionOps] = Ctx(ops=connect_client(), identity=identity)
    flags.apply_logging()
    result = asyncio.run(session_ls.execute(ctx))
    for row in result.clients:
        if row.connection_id == connection_id:
            if flags.json:
                typer.echo(_json.dumps(row.model_dump(mode="json")))
            else:
                name = row.identity.name if row.identity else "unknown"
                typer.echo(f"{row.connection_id}: {name}")
            return
    typer.echo(f"session {connection_id} not found", err=True)
    raise typer.Exit(code=1)


@session_app.command("identify")
def identify(
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
    """Declare the caller's identity to the Hub for this connection."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    ctx: Ctx[SessionOps] = Ctx(ops=connect_client(), identity=identity)
    declaration: dict[str, object] = {"kind": identity.kind, "name": identity.name}
    if identity.repo is not None:
        declaration["repo"] = identity.repo
    if identity.agent is not None:
        declaration["agent"] = identity.agent
    run(session_identify(ctx, declaration, scope=scope_for(identity)), flags)
