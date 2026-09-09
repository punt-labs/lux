"""``lux display`` — display info, theme, mode, window settings, screenshot.

``mode`` is the one fused verb left: no argument reads, an argument writes.
Theme and window are user-only gestures at the Display itself (DES-088).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

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
from punt_lux.commands.display_state_get import display_state_get
from punt_lux.operations import DisplayModeRequest
from punt_lux.operations.display_mode_store import DisplayModeStore

if TYPE_CHECKING:
    from punt_lux.commands.display_state_get import DisplayStateOps

display_app = typer.Typer(
    name="display",
    help="Display info, theme, mode, window settings, screenshot.",
    no_args_is_help=True,
)

__all__ = ["display_app"]

_ModeValue = Annotated[
    str | None, typer.Argument(help="'on' or 'off' to set the mode. Omit to read it.")
]


def _ambient_ctx[T](*, _protocol: type[T] | None = None) -> Ctx[T]:
    """Build a ``Ctx`` from the shared identity; ``_protocol`` only types the call."""
    del _protocol
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx = Ctx(ops=connect_client(identity=identity), identity=identity)
    return cast("Ctx[T]", ctx)


@display_app.command("info")
def info(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the display's backend, geometry, frame rate, and identity."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    ctx: Ctx[DisplayInfoOps] = _ambient_ctx()
    run(display_info(ctx), flags)


@display_app.command("theme")
def theme(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Get the active theme; setting it is a user gesture at Lux ▸ Settings."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    ctx: Ctx[ThemeOps] = _ambient_ctx()
    run(display_get_theme(ctx), flags)


@display_app.command("state")
def state(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Return the Display's own widget/frame state, for Hub-vs-Display comparison."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    ctx: Ctx[DisplayStateOps] = _ambient_ctx()
    run(display_state_get(ctx), flags)


async def _local_mode_result(value: str) -> CommandResult:
    """Wrap a completed local write; same shape the deleted Hub round trip produced."""
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
    """Get or set a project's display mode. --repo is always required."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    if value is None:
        ctx: Ctx[DisplayModeOps] = _ambient_ctx()
        run(display_mode_get(ctx, repo), flags)
        return
    _set_mode(value, repo, flags)


def _set_mode(value: str, repo: str, flags: OutputFlags) -> None:
    """Write the per-repo mode marker directly, or exit 1 naming the fault."""
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
    """Get window settings; changing them is a user gesture at Lux ▸ Settings."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    ctx: Ctx[WindowOps] = _ambient_ctx()
    run(display_window_get(ctx), flags)


@display_app.command("screenshot")
def screenshot(
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Capture the display framebuffer; currently unsupported (DES-028)."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    ctx: Ctx[ScreenshotOps] = _ambient_ctx()
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
    :meth:`punt_lux.luxd_display.DisplayEntryPoint.serve` — launchd/systemd
    runs the top-level ``luxd-display`` executable directly, not this.
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
