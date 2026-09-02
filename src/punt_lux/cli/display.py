"""``lux display`` — display info, theme, mode, window settings, screenshot.

``theme``/``mode``/``window`` are fused verbs: no argument reads, an argument
(or any option) writes. Under the hood that dispatches to the paired
Get/Set command singletons per the design vocabulary's fused Display group.
"""

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
from punt_lux.commands import (
    CommandResult,
    Ctx,
    DisplayInfoOps,
    DisplayModeOps,
    ScreenshotOps,
    ThemeOps,
    WindowOps,
    display_get_theme,
    display_info,
    display_mode_get,
    display_screenshot,
    display_window_get,
)
from punt_lux.operations import DisplayModeRequest
from punt_lux.operations.display_mode_store import DisplayModeStore

display_app = typer.Typer(
    name="display",
    help="Display info, theme, mode, window settings, screenshot.",
    no_args_is_help=True,
)

__all__ = ["display_app"]

_ModeValue = Annotated[
    str | None, typer.Argument(help="'on' or 'off' to set the mode. Omit to read it.")
]


@display_app.command("info")
def info(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the display's backend, geometry, frame rate, and identity."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[DisplayInfoOps] = Ctx(
        ops=connect_client(identity=identity), identity=identity
    )
    run(display_info(ctx), flags)


@display_app.command("theme")
def theme(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Get the active theme.

    Setting the theme is the user's own gesture at the Display's own
    Lux ▸ Settings menu -- never a client op (DES-088).
    """
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[ThemeOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(display_get_theme(ctx), flags)


async def _local_mode_result(value: str) -> CommandResult:
    """Wrap a completed local mode write in the shared command envelope.

    Byte-for-byte the same shape ``display_mode_set``'s deleted Hub round trip
    produced (``commands/display_mode_get.py``/the deleted
    ``display_mode_set.py`` both used ``text=f"display:{result.mode}"``) --
    ``value`` is already the CLI's own ``"on"``/``"off"`` literal, the same
    value ``DisplayModeState.mode`` would have carried.
    """
    return CommandResult(text=f"display:{value}", json_data={"mode": value})


@display_app.command("mode")
def mode(
    value: _ModeValue = None,
    repo: str = typer.Option(..., "--repo", help="Absolute path to the project."),
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Get or set a project's display mode. --repo is always required.

    Setting writes the per-repo marker file directly (``DisplayModeStore``)
    rather than routing through the Hub -- a user path to per-repo
    enable/disable belongs to the enablement/install flow, not a client
    setter (DES-088). Getting is unchanged: still Hub-routed.
    """
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    if value is None:
        identity = identity_from_flags(
            as_=None, kind=None, name=None, repo=None, agent=None
        )
        ctx: Ctx[DisplayModeOps] = Ctx(
            ops=connect_client(identity=identity), identity=identity
        )
        run(display_mode_get(ctx, repo), flags)
        return
    if value not in ("on", "off"):
        raise typer.BadParameter("mode must be 'on' or 'off'")
    repo_error = DisplayModeRequest.check_repo(repo)
    if repo_error is not None:
        typer.echo(f"error: {repo_error.reason}", err=True)
        raise typer.Exit(code=1)
    fault = DisplayModeStore(repo).write("y" if value == "on" else "n")
    if fault is not None:
        typer.echo(f"error: {fault.reason}", err=True)
        raise typer.Exit(code=1)
    run(_local_mode_result(value), flags)


@display_app.command("window")
def window(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Get window settings (opacity, font scale, decoration, idle rate).

    Changing them is the user's own gesture at the Display's own
    Lux ▸ Settings menu -- never a client op (DES-088).
    """
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[WindowOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    run(display_window_get(ctx), flags)


@display_app.command("screenshot")
def screenshot(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Capture the display framebuffer and return the image path.

    Capture is currently unsupported (DES-028, bead lux-olgj) -- the
    command reaches the Hub and returns its real error until that closes.
    """
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[ScreenshotOps] = Ctx(
        ops=connect_client(identity=identity), identity=identity
    )
    run(display_screenshot(ctx), flags)


@display_app.command("serve")
def serve(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    test_auto_click: bool = typer.Option(
        False,
        "--test-auto-click",
        help="Auto-fire click events for buttons (testing)",
    ),
) -> None:
    """Start the Lux display server (the ImGui render loop process).

    Interactive/manual entry point onto
    :meth:`punt_lux.luxd_display.DisplayEntryPoint.serve` — the process
    launchd/systemd runs directly is the top-level ``luxd-display`` executable,
    not this subcommand.
    """
    try:
        from punt_lux.luxd_display import DisplayEntryPoint
    except ModuleNotFoundError as exc:
        _display_modules = {"imgui_bundle", "numpy", "PIL", "OpenGL"}
        if exc.name and exc.name.split(".")[0] in _display_modules:
            typer.echo(
                "Display extras not installed. Run: pip install 'punt-lux[display]'",
                err=True,
            )
            raise typer.Exit(code=1) from None
        raise

    DisplayEntryPoint.serve(socket, test_auto_click=test_auto_click)
