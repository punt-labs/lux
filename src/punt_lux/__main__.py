"""CLI entry point for lux."""

from __future__ import annotations

import sys

import typer

from punt_lux import __version__
from punt_lux.cli._shared import (
    JsonFlag,
    OutputFlags,
    QuietFlag,
    VerboseFlag,
    configure_logging,
    run,
)
from punt_lux.cli.registry import PLUGIN_ID, register_subcommands
from punt_lux.hook_cli import HookCommands


def _version_callback(value: bool) -> None:
    if value:
        print(f"lux {__version__}")
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
register_subcommands(app)
HookCommands.register(hook_app)


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
    from punt_lux.cli.display_enablement import DisplayEnablement

    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    DisplayEnablement(flags).apply(on=True)


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
    from punt_lux.cli.display_enablement import DisplayEnablement

    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    DisplayEnablement(flags).apply(on=False)


@hook_app.command("session-start")
def cc_session_start() -> None:
    """SessionStart — internal hook dispatcher."""
    HookCommands.session_start()


# Admin commands


@app.command()
def version(
    *,
    json_out: JsonFlag = False,
    # Accepted for surface parity; verbose/quiet not distinguished here.
    verbose: VerboseFlag = False,
    quiet: QuietFlag = False,
) -> None:
    """Print the version."""
    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    if not quiet:
        print(f'{{"version": "{__version__}"}}' if json_out else f"lux {__version__}")


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

    ``--timeout`` (0.1-30s) is the real display-leg budget; the HTTP round-trip
    sits a margin above it, reporting the same "not running"/"timeout"/"error"
    status the MCP tool and REST route share on one code path.
    """
    from punt_lux.cli._shared import connect_client
    from punt_lux.client.cli_identity import CliIdentity
    from punt_lux.commands import Ctx as CommandCtx, PingOps, ping as ping_command
    from punt_lux.hub.display_link import DEFAULT_RECV_TIMEOUT

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

    from punt_lux.service.display_paths import DisplayPaths

    OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
    dp = DisplayPaths(Path(socket) if socket else None)
    line = dp.running_status_line()
    if not quiet:
        print(
            line[:1].upper() + line[1:]
            if line
            else f"Display not running at {dp.socket_path}"
        )
    raise typer.Exit(code=0 if line else 1)


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

    from punt_lux.service.display_paths import DisplayPaths
    from punt_lux.service.doctor_checks import EnvironmentChecks
    from punt_lux.service.doctor_report import FAIL, OK, OPTIONAL, DoctorReport

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
    checks = EnvironmentChecks(_check, PLUGIN_ID)
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
    raise typer.Exit(code=int(_check.failed > 0))


def _entry() -> None:
    """Run the Lux CLI with process-owned diagnostics."""
    configure_logging("lux", "cli")
    app()


if __name__ == "__main__":
    _entry()
