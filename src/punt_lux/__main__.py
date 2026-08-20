"""CLI entry point for lux."""

from __future__ import annotations

import sys

import typer

from punt_lux import __version__
from punt_lux.cli._shared import JsonFlag, OutputFlags, QuietFlag, VerboseFlag, run
from punt_lux.cli.beads import beads as beads_command
from punt_lux.cli.callback import callback_app
from punt_lux.cli.display import display_app
from punt_lux.cli.error import error_app
from punt_lux.cli.event import event_app
from punt_lux.cli.frame import frame_app
from punt_lux.cli.hub import hub_app
from punt_lux.cli.menu import menu_app
from punt_lux.cli.plugin import (
    _PLUGIN_ID,
    install as plugin_install,
    uninstall as plugin_uninstall,
)
from punt_lux.cli.scene import scene_app
from punt_lux.cli.session import session_app
from punt_lux.doctor_report import FAIL, OK, OPTIONAL, DoctorReport


def _print_version() -> None:
    """Print the CLI version banner."""
    print(f"lux {__version__}")


def _version_callback(value: bool) -> None:
    if value:
        _print_version()
        raise typer.Exit


app = typer.Typer(
    name="lux",
    help="lux: visual output surface for AI agents.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def _main(  # pyright: ignore[reportUnusedFunction]
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """lux: visual output surface for AI agents."""


hook_app = typer.Typer(hidden=True)
app.add_typer(hook_app, name="hook")
app.command("beads")(beads_command)
app.add_typer(hub_app, name="hub")
app.add_typer(session_app, name="session")
app.add_typer(scene_app, name="scene")
app.add_typer(frame_app, name="frame")
app.add_typer(menu_app, name="menu")
app.add_typer(display_app, name="display")
app.add_typer(event_app, name="event")
app.add_typer(error_app, name="error")
app.add_typer(callback_app, name="callback")


# Product commands


@app.command()
def enable(
    *,
    # Accepted for surface parity; verbose/quiet not currently distinguished
    # in this command, and it has no JSON payload beyond the one line below.
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Enable visual output for this project."""
    from punt_lux.config import ConfigManager

    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    ConfigManager().write_field("display", "y")
    if not quiet:
        print('{"enabled": true}' if json_out else "Lux display enabled.")


@app.command()
def disable(
    *,
    # Accepted for surface parity; verbose/quiet not currently distinguished
    # in this command, and it has no JSON payload beyond the one line below.
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Disable visual output for this project."""
    from punt_lux.config import ConfigManager

    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    ConfigManager().write_field("display", "n")
    if not quiet:
        print('{"enabled": false}' if json_out else "Lux display disabled.")


# Hook dispatcher (internal)


@hook_app.command("session-start")
def cc_session_start() -> None:
    """SessionStart — internal hook dispatcher."""
    from punt_lux.hooks import emit, handle_session_start

    # Skip stdin — this handler needs no payload and the pipe may never close.
    result = handle_session_start()
    emit(result)


# Admin commands


@app.command()
def version(
    *,
    json_out: JsonFlag = False,
    # Accepted for surface parity; verbose/quiet not currently distinguished
    # in this command.
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Print the version."""
    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    if quiet:
        return
    if json_out:
        print(f'{{"version": "{__version__}"}}')
    else:
        print(f"lux {__version__}")


_PING_HTTP_MARGIN_SECONDS = 2.0  # HTTP bound sits a margin above the display leg


@app.command()
def ping(
    # None derives the wait from the display budget; bounds match the route so
    # an out-of-range value is a clear typer error (clamp defaults off), not HTTP.
    timeout: float | None = typer.Option(
        None, "--timeout", "-t", min=0.1, max=30, help="Seconds to wait for the ping."
    ),
    *,
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Ping the display through luxd and print round-trip time.

    ``--timeout`` (0.1-30s) is the real display-leg budget over luxd's REST API;
    the HTTP round-trip sits a margin above it, so a slow display reports "timeout".
    Routes through the shared ``ping`` command singleton and prints its rendered
    line directly — the same three-way status ("not running" / "timeout" /
    "error: <reason>") the MCP tool and REST route report, on one code path.
    """
    from punt_lux.cli._shared import connect_client
    from punt_lux.cli_identity import CliIdentity
    from punt_lux.commands import Ctx as CommandCtx, PingOps, ping as ping_command
    from punt_lux.domain.hub.display_link import DEFAULT_RECV_TIMEOUT

    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    display_wait = timeout if timeout is not None else DEFAULT_RECV_TIMEOUT
    http_timeout = display_wait + _PING_HTTP_MARGIN_SECONDS

    client = connect_client(timeout=http_timeout)
    ctx: CommandCtx[PingOps] = CommandCtx(ops=client, identity=CliIdentity.resolve())
    run(ping_command(ctx, timeout), flags)


@app.command()
def status(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    *,
    # Accepted for surface parity; verbose/quiet not currently distinguished
    # in this command, and its output has no JSON payload yet.
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Check whether the display server is running."""
    from pathlib import Path

    from punt_lux.paths import DisplayPaths

    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    dp = DisplayPaths(Path(socket) if socket else None)
    path = dp.socket_path
    running = dp.is_running()

    if not quiet:
        if running:
            try:
                pid = int(dp.pid_path.read_text().strip())
                print(f"Display running (pid {pid}) at {path}")
            except (OSError, ValueError):
                print(f"Display running at {path} (pid unknown)")
        else:
            print(f"Display not running at {path}")

    raise typer.Exit(code=0 if running else 1)


@app.command()
def doctor(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    *,
    # Accepted for surface parity; verbose/quiet not currently distinguished
    # in this command, and its output has no JSON payload yet.
    json_out: JsonFlag = False,
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Check installation health."""
    from pathlib import Path

    from punt_lux.doctor_checks import EnvironmentChecks
    from punt_lux.paths import DisplayPaths

    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    _check = DoctorReport()

    # Python version
    v = sys.version_info
    if v >= (3, 13):
        _check(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _check(
            FAIL,
            f"Python {v.major}.{v.minor}.{v.micro} (requires 3.13+)",
        )

    # imgui-bundle (part of display extras)
    try:
        from imgui_bundle import (
            imgui,  # noqa: F401  # pyright: ignore[reportUnusedImport]
        )

        _check(OK, "imgui-bundle installed")
    except ImportError:
        _check(
            OPTIONAL,
            "imgui-bundle not installed (run: pip install 'punt-lux[display]')",
            required=False,
        )

    # Fonts and the plugin are the machine's business, not lux's — advisory
    # either way, so a missing one never fails the run.
    checks = EnvironmentChecks(_check, _PLUGIN_ID)
    checks.fonts()

    # Display server
    dp = DisplayPaths(Path(socket) if socket else None)
    path = dp.socket_path
    if dp.is_running():
        _check(OK, f"Display server running at {path}")
    else:
        _check(OPTIONAL, f"Display server not running at {path}", required=False)

    checks.plugin()

    if not quiet:
        print(_check.render())
    if _check.failed > 0:
        raise typer.Exit(code=1)


app.command()(plugin_install)
app.command()(plugin_uninstall)


if __name__ == "__main__":
    app()
