"""Register checkout integration, diagnostics, and Claude Code hook commands."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from punt_lux.cli._shared import (
    JsonFlag,
    OutputFlags,
    QuietFlag,
    VerboseFlag,
)
from punt_lux.cli.hook_cli import HookCommands
from punt_lux.cli.registry import PLUGIN_ID
from punt_lux.cli.repo_enablement import RepoCommands
from punt_lux.service.hooks import emit, handle_session_start
from punt_lux.service.repo_activation import Checkout


class RootCommands:
    @staticmethod
    def register(app: typer.Typer) -> None:
        hooks = typer.Typer(hidden=True)
        app.add_typer(hooks, name="hook")
        HookCommands.register(hooks)
        hooks.command("session-start")(RootCommands.session_start)
        RepoCommands.register(app)
        app.command()(RootCommands.status)
        app.command()(RootCommands.doctor)

    @staticmethod
    def session_start() -> None:
        """Return display context without waiting for hook stdin to close."""
        if Checkout.enabled_at(Path.cwd()) is None:
            return
        HookCommands.configure_logging()
        emit(handle_session_start())

    @staticmethod
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
        from punt_lux.service.display_paths import DisplayPaths

        OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet).apply_logging()
        dp = DisplayPaths(Path(socket) if socket else None)
        line = dp.running_status_line()
        if not quiet:
            print(RepoCommands.status_line())
            print(
                line[:1].upper() + line[1:]
                if line
                else f"Display not running at {dp.socket_path}"
            )
        raise typer.Exit(code=0 if line else 1)

    @staticmethod
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
        _check(OPTIONAL, RepoCommands.status_line(), required=False)

        if not quiet:
            print(_check.render())
        raise typer.Exit(code=int(_check.failed > 0))
