"""CLI adapter for the Lux repository integration."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from punt_lux.cli._shared import JsonFlag, OutputFlags, QuietFlag, VerboseFlag
from punt_lux.service.enablement import Action, Enablement
from punt_lux.service.repo_activation import Checkout


class EnablementScope(StrEnum):
    PROJECT = "project"
    LOCAL = "local"


class RepoCommands:
    @classmethod
    def register(cls, app: typer.Typer) -> None:
        app.command("enable")(cls.enable)
        app.command("disable")(cls.disable)

    @staticmethod
    def enable(
        *,
        scope: Annotated[
            EnablementScope, typer.Option("--scope")
        ] = EnablementScope.LOCAL,
        refresh: Annotated[
            bool, typer.Option("--refresh", help="Replace the deposited user guide.")
        ] = False,
        clear_opt_out: Annotated[bool, typer.Option("--clear-opt-out")] = False,
        json_out: JsonFlag = False,
        verbose: VerboseFlag = False,
        quiet: QuietFlag = False,
    ) -> None:
        """Enable Lux integration in this checkout (or for the whole repo)."""
        flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
        apply("enable", scope, flags, refresh=refresh, clear_opt_out=clear_opt_out)

    @staticmethod
    def disable(
        *,
        scope: Annotated[
            EnablementScope, typer.Option("--scope")
        ] = EnablementScope.LOCAL,
        opt_out: Annotated[bool, typer.Option("--opt-out")] = False,
        json_out: JsonFlag = False,
        verbose: VerboseFlag = False,
        quiet: QuietFlag = False,
    ) -> None:
        """Disable Lux integration in this checkout (or for the whole repo)."""
        flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
        apply("disable", scope, flags, opt_out=opt_out)


def apply(
    action: Action,
    scope: EnablementScope,
    flags: OutputFlags,
    *,
    refresh: bool = False,
    opt_out: bool = False,
    clear_opt_out: bool = False,
) -> None:
    flags.apply_logging()
    try:
        update = Enablement(
            Checkout.resolve(Path.cwd()),
            "project" if scope is EnablementScope.PROJECT else "local",
        )
        result = update.apply(
            action, refresh=refresh, opt_out=opt_out, clear_opt_out=clear_opt_out
        )
    except (OSError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    if not flags.quiet:
        typer.echo(
            json.dumps(
                {"enabled": result.enabled, "deciding_file": str(result.deciding_file)}
            )
            if flags.json
            else result.describe()
        )


def repo_status() -> str:
    try:
        return Checkout.resolve(Path.cwd()).state().describe()
    except ValueError:
        return "Lux repo integration: off (no git checkout)"
