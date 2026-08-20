"""``lux install`` / ``lux uninstall`` — Claude Code plugin marketplace ops.

Admin-tier top-level singletons: register or remove the ``lux@punt-labs``
plugin under the user's Claude Code scope. Both shell out to ``claude plugin
install|uninstall`` and exit 1 on failure.
"""

from __future__ import annotations

import shutil
import subprocess

import typer

__all__ = ["_PLUGIN_ID", "install", "uninstall"]

_PLUGIN_ID = "lux@punt-labs"


def _claude_bin() -> str:
    """Resolve the ``claude`` CLI binary or exit with a helpful message."""
    claude = shutil.which("claude")
    if not claude:
        typer.echo("Error: claude CLI not found on PATH", err=True)
        raise typer.Exit(code=1)
    return claude


def install() -> None:
    """Install the Claude Code plugin via the punt-labs marketplace."""
    result = subprocess.run(  # noqa: S603
        [_claude_bin(), "plugin", "install", _PLUGIN_ID, "--scope", "user"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("Error: plugin install failed", err=True)
        raise typer.Exit(code=1)
    typer.echo("Installed. Restart Claude Code to activate.")


def uninstall() -> None:
    """Uninstall the Claude Code plugin."""
    result = subprocess.run(  # noqa: S603
        [_claude_bin(), "plugin", "uninstall", _PLUGIN_ID, "--scope", "user"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("Error: plugin uninstall failed", err=True)
        raise typer.Exit(code=1)
    typer.echo("Uninstalled.")
