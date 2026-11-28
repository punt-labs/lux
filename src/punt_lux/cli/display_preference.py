"""CLI writes to the personal display preference without a Hub round trip."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Self

import typer

from punt_lux.cli._shared import JsonFlag, OutputFlags, QuietFlag, VerboseFlag, run
from punt_lux.commands import CommandResult, Ctx, DisplayModeOps, display_mode_get
from punt_lux.service.display_mode_store import DisplayModeStore
from punt_lux.wire.operations.config import DisplayModeRequest

_ModeValue = Annotated[
    str | None, typer.Argument(help="'on' or 'off' to set the mode. Omit to read it.")
]


class DisplayModeCommand:
    _context: Callable[[], Ctx[DisplayModeOps]]
    __slots__ = ("_context",)

    def __new__(cls, context: Callable[[], Ctx[DisplayModeOps]]) -> Self:
        self = super().__new__(cls)
        self._context = context
        return self

    def register(self, app: typer.Typer) -> None:
        app.command("mode")(self.mode)

    def mode(
        self,
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
            ctx = self._context()
            run(display_mode_get(ctx, repo), flags)
            return
        self._set_mode(value, repo, flags)

    @staticmethod
    async def _local_mode_result(value: str) -> CommandResult:
        """Return a local write in the standard display mode result shape."""
        return CommandResult(text=f"display:{value}", json_data={"mode": value})

    @staticmethod
    def _set_mode(value: str, repo: str, flags: OutputFlags) -> None:
        """Write only the personal display preference."""
        if value not in ("on", "off"):
            raise typer.BadParameter("mode must be 'on' or 'off'")
        fault = DisplayModeRequest.check_repo(repo)
        if fault is None:
            fault = DisplayModeStore(repo).write("y" if value == "on" else "n")
        if fault is not None:
            typer.echo(f"error: {fault.reason}", err=True)
            raise typer.Exit(code=1)
        run(DisplayModeCommand._local_mode_result(value), flags)
