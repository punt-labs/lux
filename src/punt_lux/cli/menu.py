"""``lux menu`` — list and set the Hub-owned menu bar.

``menu get`` (one entry) is in the design vocabulary but has no
``commands/`` singleton yet (only ``menu_ls``/``menu_set`` shipped in .3);
shipping it here would mean writing a new command class outside this
mission's write set, so it is not shipped until that command exists.
"""

from __future__ import annotations

from pathlib import Path
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
    read_json_array,
    run,
)
from punt_lux.commands import Ctx, MenuOps, menu_ls, menu_set
from punt_lux.operations import OpError, SetMenuRequest

menu_app = typer.Typer(
    name="menu",
    help="List and set the Hub-owned menu bar.",
    no_args_is_help=True,
)

__all__ = ["menu_app"]

_FromFile = Annotated[
    Path | None, typer.Option("--from", help="Read the JSON entries array from a file.")
]
_Entries = Annotated[
    str | None,
    typer.Argument(help="Inline JSON entries array. Omit to read stdin/--from."),
]


@menu_app.command("ls")
def ls(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the Hub-authoritative menu bar."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[MenuOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(menu_ls(ctx), flags)


@menu_app.command("set")
def set_(
    entries: _Entries = None,
    from_file: _FromFile = None,
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
    """Replace the Hub-owned menu bar. Body is a JSON array of menu entries."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    raw = read_json_array(entries, from_file)
    request = SetMenuRequest.parse(raw)
    if isinstance(request, OpError):
        typer.echo(f"error: {request.reason}", err=True)
        raise typer.Exit(code=1)
    ctx: Ctx[MenuOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(menu_set(ctx, request), flags)
