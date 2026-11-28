"""``lux display`` — display info, theme, mode, window settings, screenshot.

``mode`` is the one fused verb left: no argument reads, an argument writes.
Theme and window are user-only gestures at the Display itself (DES-088).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import typer

from punt_lux.cli._shared import (
    JsonFlag,
    OutputFlags,
    QuietFlag,
    VerboseFlag,
    connect_client,
    identity_from_flags,
    run,
    scope_for,
)
from punt_lux.cli.display_preference import DisplayModeCommand
from punt_lux.commands import (
    Ctx,
    DisplayInfoOps,
    DisplayModeOps,
    ScreenshotOps,
    ThemeOps,
    WindowOps,
    display_get_theme,
    display_info,
    display_screenshot,
    display_window_get,
)
from punt_lux.commands.display_state_get import display_state_get

if TYPE_CHECKING:
    from punt_lux.wire.ops.display_state import DisplayStateOps

display_app = typer.Typer(
    name="display",
    help="Display info, theme, mode, window settings, screenshot.",
    no_args_is_help=True,
)

__all__ = ["display_app"]


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
    """Return your own widget/frame state, for Hub-vs-Display comparison."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    ctx: Ctx[DisplayStateOps] = _ambient_ctx()
    run(display_state_get(ctx, scope=scope_for(ctx.identity)), flags)


DisplayModeCommand(lambda: _ambient_ctx(_protocol=DisplayModeOps)).register(display_app)


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
    """Capture the next painted frame to a PNG on the display host."""
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
    """Start the display server in the foreground."""
    from punt_lux.service.display_foreground import DisplayForeground

    try:
        DisplayForeground.serve(socket, test_auto_click=test_auto_click)
    except ModuleNotFoundError as exc:
        if exc.name and DisplayForeground.is_dependency(exc.name):
            typer.echo(
                "Display extras not installed. Run: pip install 'punt-lux[display]'",
                err=True,
            )
            raise typer.Exit(code=1) from None
        raise
