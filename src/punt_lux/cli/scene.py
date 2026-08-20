"""``lux scene`` — install, patch, clear, inspect, and list scenes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

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
    read_json_payload,
    run,
    scope_for,
)
from punt_lux.commands import (
    Ctx,
    SceneOps,
    scene_clear,
    scene_clear_all,
    scene_dashboard,
    scene_inspect,
    scene_ls,
    scene_show,
    scene_table,
    scene_update,
)
from punt_lux.operations import (
    InspectScope,
    OpError,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    UpdateRequest,
)

scene_app = typer.Typer(
    name="scene",
    help="Install, patch, clear, inspect, and list scenes.",
    no_args_is_help=True,
)

__all__ = ["scene_app"]

_FromFile = Annotated[
    Path | None, typer.Option("--from", help="Read the JSON payload from a file.")
]
_Payload = Annotated[
    str | None, typer.Argument(help="Inline JSON payload. Omit to read stdin/--from.")
]


def _fail(err: OpError) -> None:
    """Report a parse-time ``OpError`` and exit 1, matching the command envelope."""
    typer.echo(f"error: {err.reason}", err=True)
    raise typer.Exit(code=1)


@scene_app.command("show")
def show(
    scene_id: Annotated[str, typer.Argument(help="Scene id to install.")],
    payload: _Payload = None,
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
    """Install or replace a scene. Body is a RenderRequest JSON object."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    raw = read_json_payload(payload, from_file)
    raw.setdefault("scene_id", scene_id)
    request = RenderRequest.parse(raw)
    if isinstance(request, OpError):
        _fail(request)
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_show(ctx, request, scope=scope_for(identity)), flags)


@scene_app.command("update")
def update(
    scene_id: Annotated[str, typer.Argument(help="Scene id to patch.")],
    payload: _Payload = None,
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
    """Apply a patch batch. Body is a JSON object: {"patches": [...]}."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    raw = read_json_payload(payload, from_file)
    patches_raw = raw.get("patches", [])
    if not isinstance(patches_raw, list):
        raise typer.BadParameter("payload must contain a 'patches' array")
    request = UpdateRequest.parse(cast("list[object]", patches_raw))
    if isinstance(request, OpError):
        _fail(request)
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_update(ctx, scene_id, request, scope=scope_for(identity)), flags)


@scene_app.command("clear")
def clear(
    scene_id: Annotated[str, typer.Argument(help="Scene id to remove.")],
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
    """Remove one scene the caller owns."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_clear(ctx, scene_id, scope=scope_for(identity)), flags)


@scene_app.command("clear-all")
def clear_all(
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
    """Remove every scene the caller owns."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_clear_all(ctx, scope=scope_for(identity)), flags)


@scene_app.command("inspect")
def inspect(
    scene_id: Annotated[str, typer.Argument(help="Scene id to inspect.")],
    want_geometry: Annotated[
        bool,
        typer.Option("--geometry", help="Include painted element/frame rects."),
    ] = False,
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
    """Return the caller's own scene tree."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    facts = InspectScope(want_geometry=want_geometry)
    run(
        scene_inspect(ctx, scene_id, scope=scope_for(identity), facts=facts),
        flags,
    )


@scene_app.command("ls")
def ls(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """List every live scene and frame (caller-scoped)."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_ls(ctx), flags)


@scene_app.command("table")
def table(
    scene_id: Annotated[str, typer.Argument(help="Scene id for the table.")],
    payload: _Payload = None,
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
    """Render a Hub-composed filterable table. Body is a RenderTableRequest."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    raw = read_json_payload(payload, from_file)
    raw.setdefault("scene_id", scene_id)
    request = RenderTableRequest.parse(raw)
    if isinstance(request, OpError):
        _fail(request)
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_table(ctx, request, scope=scope_for(identity)), flags)


@scene_app.command("dashboard")
def dashboard(
    scene_id: Annotated[str, typer.Argument(help="Scene id for the dashboard.")],
    payload: _Payload = None,
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
    """Render a metrics/charts/table dashboard. Body is a RenderDashboardRequest."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    raw = read_json_payload(payload, from_file)
    raw.setdefault("scene_id", scene_id)
    request = RenderDashboardRequest.parse(raw)
    if isinstance(request, OpError):
        _fail(request)
    ctx: Ctx[SceneOps] = Ctx(ops=connect_client(), identity=identity)
    run(scene_dashboard(ctx, request, scope=scope_for(identity)), flags)
