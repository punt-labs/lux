"""``lux display`` — display info, theme, mode, window settings, screenshot.

``theme``/``mode``/``window`` are fused verbs: no argument reads, an argument
(or any option) writes. Under the hood that dispatches to the paired
Get/Set command singletons per the design vocabulary's fused Display group.
"""

from __future__ import annotations

import logging
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
    Ctx,
    DisplayInfoOps,
    DisplayModeOps,
    ScreenshotOps,
    ThemeOps,
    WindowOps,
    display_get_theme,
    display_info,
    display_mode_get,
    display_mode_set,
    display_screenshot,
    display_set_theme,
    display_window_get,
    display_window_set,
)
from punt_lux.log_level import level_from_env
from punt_lux.operations import (
    DisplayModeRequest,
    OpError,
    SetThemeRequest,
    WindowSettingsPatch,
)

display_app = typer.Typer(
    name="display",
    help="Display info, theme, mode, window settings, screenshot.",
    no_args_is_help=True,
)

__all__ = ["display_app"]

_ThemeName = Annotated[
    str | None,
    typer.Argument(help="Theme name to switch to. Omit to read the current theme."),
]
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
    name: _ThemeName = None,
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Get the active theme, or set it when NAME is given."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[ThemeOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    if name is None:
        run(display_get_theme(ctx), flags)
        return
    request = SetThemeRequest.parse(name)
    if isinstance(request, OpError):
        typer.echo(f"error: {request.reason}", err=True)
        raise typer.Exit(code=1)
    run(display_set_theme(ctx, request), flags)


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
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[DisplayModeOps] = Ctx(
        ops=connect_client(identity=identity), identity=identity
    )
    if value is None:
        run(display_mode_get(ctx, repo), flags)
        return
    # DisplayModeRequest.parse speaks the shared y/n toggle vocabulary (the
    # same one set_display_mode's MCP tool takes); on/off is this verb's
    # own human-readable spelling, translated here rather than widening the
    # shared model's vocabulary.
    if value not in ("on", "off"):
        raise typer.BadParameter("mode must be 'on' or 'off'")
    toggle = "y" if value == "on" else "n"
    request = DisplayModeRequest.parse(toggle, repo)
    if isinstance(request, OpError):
        typer.echo(f"error: {request.reason}", err=True)
        raise typer.Exit(code=1)
    run(display_mode_set(ctx, request), flags)


@display_app.command("window")
def window(
    opacity: float | None = typer.Option(None, help="Window opacity (0.0-1.0)."),
    font_scale: float | None = typer.Option(None, help="UI font scale factor."),
    decorated: bool | None = typer.Option(
        None,
        "--decorated/--no-decorated",
        help="Show or hide window chrome. Omit to leave unchanged.",
    ),
    fps_idle: float | None = typer.Option(None, help="Idle render rate (fps)."),
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Get window settings, or set any given option."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=None, kind=None, name=None, repo=None, agent=None
    )
    ctx: Ctx[WindowOps] = Ctx(ops=connect_client(identity=identity), identity=identity)
    if (
        opacity is None
        and font_scale is None
        and decorated is None
        and fps_idle is None
    ):
        run(display_window_get(ctx), flags)
        return
    patch = WindowSettingsPatch(
        opacity=opacity, font_scale=font_scale, decorated=decorated, fps_idle=fps_idle
    )
    run(display_window_set(ctx, patch), flags)


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

    This is the process luxd spawns (``lux display serve``) — not a verb an
    agent or human runs interactively.
    """
    from pathlib import Path

    from punt_lux.paths import DisplayPaths

    try:
        from punt_lux.display import RenderLoop
    except ModuleNotFoundError as exc:
        _display_modules = {"imgui_bundle", "numpy", "PIL", "OpenGL"}
        if exc.name and exc.name.split(".")[0] in _display_modules:
            typer.echo(
                "Display extras not installed. Run: pip install 'punt-lux[display]'",
                err=True,
            )
            raise typer.Exit(code=1) from None
        raise

    dp = DisplayPaths(Path(socket) if socket else None)
    log_path = dp.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=str(log_path),
        level=level_from_env("INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    server = RenderLoop(socket, test_auto_click=test_auto_click)
    server.run()
