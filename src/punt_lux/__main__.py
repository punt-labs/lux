"""CLI entry point for lux."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Protocol

import typer

app = typer.Typer(
    name="lux",
    help="lux: visual output surface for AI agents.",
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# Symbols for doctor output
# ---------------------------------------------------------------------------

_OK = "\u2713"  # ✓
_FAIL = "\u2717"  # ✗
_OPTIONAL = "\u2014"  # —

_PLUGIN_ID = "lux@punt-labs"


class _CheckFn(Protocol):
    def __call__(self, symbol: str, message: str, *, required: bool = True) -> None: ...


# ---------------------------------------------------------------------------
# Product commands
# ---------------------------------------------------------------------------


@app.command()
def display(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    test_auto_click: bool = typer.Option(
        False,
        "--test-auto-click",
        help="Auto-fire click events for buttons (testing)",
    ),
) -> None:
    """Start the Lux display server."""
    from punt_lux.display import DisplayServer

    server = DisplayServer(socket, test_auto_click=test_auto_click)
    server.run()


@app.command()
def serve() -> None:
    """Start the Lux MCP server (stdio transport)."""
    from punt_lux.server import mcp

    mcp.run(transport="stdio")


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the version."""
    from punt_lux import __version__

    print(f"lux {__version__}")


@app.command()
def status(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Check whether the display server is running."""
    from pathlib import Path

    from punt_lux.paths import default_socket_path, is_display_running, pid_file_path

    path = Path(socket) if socket else default_socket_path()
    running = is_display_running(path)

    if running:
        try:
            pid = int(pid_file_path(path).read_text().strip())
            print(f"Display running (pid {pid}) at {path}")
        except (OSError, ValueError):
            print(f"Display running at {path} (pid unknown)")
    else:
        print(f"Display not running at {path}")

    raise typer.Exit(code=0 if running else 1)


def _check_fonts(_check: _CheckFn) -> None:
    """Check for system fonts used by the display server."""
    import platform
    from pathlib import Path

    def _first_existing(*candidates: str) -> str | None:
        for p in candidates:
            if Path(p).is_file():
                return p
        return None

    if platform.system() == "Darwin":
        primary = _first_existing(
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        )
        sym = _first_existing("/System/Library/Fonts/Apple Symbols.ttf")
        hint = ""  # macOS always has these
    else:
        primary = _first_existing(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        )
        sym = _first_existing(
            "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
            "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
        )
        hint = " \u2014 apt install fonts-dejavu-core or fonts-noto"

    if primary:
        _check(_OK, f"Font: {primary}", required=False)
    else:
        _check(_FAIL, f"No Unicode font found{hint} (falls back to Latin-only)", required=False)

    if sym:
        _check(_OK, f"Symbol font: {sym}", required=False)
    else:
        _check(_OPTIONAL, "No symbol font found (math symbols may not render)", required=False)


def _check_plugin(
    _check: _CheckFn,
) -> None:
    """Check Claude CLI and plugin registration (optional)."""
    claude = shutil.which("claude")
    if claude:
        _check(_OK, f"claude CLI: {claude}", required=False)
    else:
        _check(_OPTIONAL, "claude CLI not found (needed for plugin)", required=False)
        return

    result = subprocess.run(  # noqa: S603
        [claude, "plugin", "list"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if _PLUGIN_ID in result.stdout:
        _check(_OK, f"Plugin: {_PLUGIN_ID}", required=False)
    else:
        _check(
            _OPTIONAL,
            "Plugin not installed (run 'lux install')",
            required=False,
        )


@app.command()
def doctor(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
) -> None:
    """Check installation health."""
    from pathlib import Path

    from punt_lux.paths import default_socket_path, is_display_running

    passed = 0
    failed = 0
    lines: list[str] = []

    def _check(symbol: str, message: str, *, required: bool = True) -> None:
        nonlocal passed, failed
        lines.append(f"{symbol} {message}")
        if symbol == _OK:
            passed += 1
        elif symbol == _FAIL and required:
            failed += 1

    # Python version
    v = sys.version_info
    if v >= (3, 13):
        _check(_OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _check(
            _FAIL,
            f"Python {v.major}.{v.minor}.{v.micro} (requires 3.13+)",
        )

    # imgui-bundle
    try:
        from imgui_bundle import (
            imgui,  # noqa: F401  # pyright: ignore[reportUnusedImport]
        )

        _check(_OK, "imgui-bundle installed")
    except ImportError:
        _check(_FAIL, "imgui-bundle not installed")

    # Fonts (not required — falls back to ImGui default, but Unicode won't render)
    _check_fonts(_check)

    # Display server
    path = Path(socket) if socket else default_socket_path()
    if is_display_running(path):
        _check(_OK, f"Display server running at {path}")
    else:
        _check(_OPTIONAL, f"Display server not running at {path}", required=False)

    # Claude CLI + plugin registration (optional)
    _check_plugin(_check)

    print("=" * 40)
    for line in lines:
        print(line)
    print("=" * 40)
    print(f"{passed} passed, {failed} failed")

    if failed > 0:
        raise typer.Exit(code=1)


@app.command()
def install() -> None:
    """Install the Claude Code plugin via the punt-labs marketplace."""
    claude = shutil.which("claude")
    if not claude:
        typer.echo("Error: claude CLI not found on PATH", err=True)
        raise typer.Exit(code=1)

    result = subprocess.run(  # noqa: S603
        [claude, "plugin", "install", _PLUGIN_ID, "--scope", "user"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("Error: plugin install failed", err=True)
        raise typer.Exit(code=1)
    print("Installed. Restart Claude Code to activate.")


@app.command()
def uninstall() -> None:
    """Uninstall the Claude Code plugin."""
    claude = shutil.which("claude")
    if not claude:
        typer.echo("Error: claude CLI not found on PATH", err=True)
        raise typer.Exit(code=1)

    result = subprocess.run(  # noqa: S603
        [claude, "plugin", "uninstall", _PLUGIN_ID, "--scope", "user"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("Error: plugin uninstall failed", err=True)
        raise typer.Exit(code=1)
    print("Uninstalled.")


if __name__ == "__main__":
    app()
