"""CLI entry point for lux."""

from __future__ import annotations

from importlib import metadata

import typer

from punt_lux.cli._shared import (
    JsonFlag,
    OutputFlags,
    QuietFlag,
    VerboseFlag,
    configure_logging,
    run,
)
from punt_lux.cli.registry import register_subcommands
from punt_lux.cli.root_commands import RootCommands


def _version_callback(value: bool) -> None:
    if value:
        print(f"lux {metadata.version('punt-lux')}")
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


register_subcommands(app)
RootCommands.register(app)


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
        current = metadata.version("punt-lux")
        print(f'{{"version": "{current}"}}' if json_out else f"lux {current}")


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
    from punt_lux.kernel.display_defaults import DEFAULT_RECV_TIMEOUT

    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    display_wait = timeout if timeout is not None else DEFAULT_RECV_TIMEOUT
    http_timeout = display_wait + _PING_HTTP_MARGIN_SECONDS

    client = connect_client(timeout=http_timeout)
    ctx: CommandCtx[PingOps] = CommandCtx(ops=client, identity=CliIdentity.resolve())
    run(ping_command(ctx, timeout), flags)


def _entry() -> None:
    """Run the Lux CLI with process-owned diagnostics."""
    configure_logging("lux", "cli")
    app()


if __name__ == "__main__":
    _entry()
