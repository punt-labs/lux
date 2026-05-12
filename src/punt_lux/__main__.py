"""CLI entry point for lux."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Protocol

import typer

from punt_lux.show import show_app

app = typer.Typer(
    name="lux",
    help="lux: visual output surface for AI agents.",
    no_args_is_help=True,
)

hook_app = typer.Typer(hidden=True)
app.add_typer(hook_app, name="hook")
app.add_typer(show_app, name="show")

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
    import logging
    from pathlib import Path

    from punt_lux.paths import default_socket_path, log_file_path

    try:
        from punt_lux.display import DisplayServer
    except ModuleNotFoundError as exc:
        _display_modules = {"imgui_bundle", "numpy", "PIL", "OpenGL"}
        if exc.name and exc.name.split(".")[0] in _display_modules:
            typer.echo(
                "Display extras not installed. Run: pip install 'punt-lux[display]'",
                err=True,
            )
            raise typer.Exit(code=1) from None
        raise

    sock_path = Path(socket) if socket else default_socket_path()
    log_path = log_file_path(sock_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    server = DisplayServer(socket, test_auto_click=test_auto_click)
    server.run()


@app.command()
def serve() -> None:
    """Start the Lux MCP server (stdio transport)."""
    from punt_lux.tools import mcp

    mcp.run(transport="stdio")


@app.command()
def enable() -> None:
    """Enable visual output for this project."""
    from punt_lux.config import resolve_config_path, write_field

    write_field("display", "y", resolve_config_path())
    print("Lux display enabled.")


@app.command()
def disable() -> None:
    """Disable visual output for this project."""
    from punt_lux.config import resolve_config_path, write_field

    write_field("display", "n", resolve_config_path())
    print("Lux display disabled.")


# ---------------------------------------------------------------------------
# Hook dispatcher (internal)
# ---------------------------------------------------------------------------


@hook_app.command("session-start")
def cc_session_start() -> None:
    """SessionStart — internal hook dispatcher."""
    from punt_lux.hooks import emit, handle_session_start

    # Handler doesn't use stdin data — skip reading entirely (DES-027).
    result = handle_session_start()
    emit(result)


@hook_app.command("post-bash")
def cc_post_bash() -> None:
    """PostToolUse Bash — internal hook dispatcher."""
    from punt_lux.hooks import handle_post_bash, read_hook_input

    data = read_hook_input()
    handle_post_bash(data)


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the version."""
    from punt_lux import __version__

    print(f"lux {__version__}")


@app.command()
def ping(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Timeout in seconds"),
) -> None:
    """Ping the display server and print round-trip time."""
    import time
    from pathlib import Path

    from punt_lux.paths import default_socket_path, is_display_running

    path = Path(socket) if socket else default_socket_path()
    if not is_display_running(path):
        print("Display not running")
        raise typer.Exit(code=1)

    from punt_lux.display_client import DisplayClient

    try:
        with DisplayClient(
            str(path), name="ping", recv_timeout=timeout, auto_spawn=False
        ) as client:
            t0 = time.monotonic()
            pong = client.ping()
            rtt = time.monotonic() - t0
    except (OSError, TimeoutError, RuntimeError):
        print("timeout")
        raise typer.Exit(code=1) from None

    if pong is None:
        print("timeout")
        raise typer.Exit(code=1)

    print(f"pong rtt={rtt:.3f}s")


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
        math = _first_existing(
            "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
            "/Library/Fonts/STIXTwoMath.otf",
        )
        hint = ""  # macOS always has these
        math_hint = ""  # ships with macOS
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
        math = _first_existing(
            "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
            "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
        )
        hint = " \u2014 apt install fonts-dejavu-core or fonts-noto"
        math_hint = " \u2014 apt install fonts-noto"

    if primary:
        _check(_OK, f"Font: {primary}", required=False)
    else:
        msg = f"No Unicode font found{hint} (falls back to Latin-only)"
        _check(_FAIL, msg, required=False)

    if sym:
        _check(_OK, f"Symbol font: {sym}", required=False)
    else:
        _check(
            _OPTIONAL,
            "No symbol font found (math symbols may not render)",
            required=False,
        )

    if math:
        _check(_OK, f"Math font: {math}", required=False)
    else:
        _check(
            _OPTIONAL,
            f"No math font found{math_hint}"
            " (Z notation double-struck letters may not render)",
            required=False,
        )


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

    # imgui-bundle (part of display extras)
    try:
        from imgui_bundle import (
            imgui,  # noqa: F401  # pyright: ignore[reportUnusedImport]
        )

        _check(_OK, "imgui-bundle installed")
    except ImportError:
        _check(
            _OPTIONAL,
            "imgui-bundle not installed (run: pip install 'punt-lux[display]')",
            required=False,
        )

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


@app.command("hub-install")
def hub_install() -> None:
    """Register luxd as a system service (launchd/systemd)."""
    from punt_lux.service import install as service_install

    print(service_install())


@app.command("hub-uninstall")
def hub_uninstall() -> None:
    """Remove luxd system service."""
    from punt_lux.service import uninstall as service_uninstall

    print(service_uninstall())


@app.command("ensure-hub")
def ensure_hub(
    restart: bool = typer.Option(False, "--restart", help="Restart luxd if running"),
) -> None:
    """Ensure luxd is running. Restart if --restart flag is set."""
    import os as _os
    import signal
    import time

    from punt_lux.paths import hub_pid_path, is_hub_running, read_hub_port

    if restart and is_hub_running():
        pid_path = hub_pid_path()
        try:
            pid = int(pid_path.read_text().strip())
            _os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to luxd (pid {pid}), waiting for restart...")
        except (ValueError, OSError) as exc:
            print(f"Could not signal luxd: {exc}")
            raise typer.Exit(code=1) from None

        # Wait for launchd/systemd to restart it
        for _ in range(20):  # 10 seconds
            time.sleep(0.5)
            if is_hub_running():
                port = read_hub_port()
                if port is not None:
                    print(f"luxd restarted (port {port})")
                else:
                    print("luxd restarted (port file not yet written)")
                return
        print("luxd did not restart within 10s")
        raise typer.Exit(code=1)

    if is_hub_running():
        port = read_hub_port()
        if port is not None:
            print(f"luxd running (port {port})")
        else:
            print("luxd running (port unknown)")
    else:
        print("luxd not running. Run 'lux hub-install' to register the service.")
        raise typer.Exit(code=1)


@app.command("hub-status")
def hub_status() -> None:
    """Show luxd hub status."""
    import json
    import urllib.request

    from punt_lux.paths import hub_pid_path, is_hub_running, read_hub_port

    if not is_hub_running():
        print("luxd not running")
        raise typer.Exit(code=1)

    pid_path = hub_pid_path()
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        pid = None

    port = read_hub_port()
    if port is None:
        print(f"luxd running (pid {pid}) but port file unreadable")
        raise typer.Exit(code=1)

    # Try to hit the health endpoint
    try:
        url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
            data = json.loads(resp.read())
        sessions = data.get("sessions", 0)
        print(f"luxd running (pid {pid}, port {port})")
        print(f"  sessions: {sessions}")
    except Exception as exc:  # noqa: BLE001
        print(f"luxd running (pid {pid}, port {port}) but health check failed: {exc}")


@app.command("setup-proxy")
def setup_proxy(
    url: str = typer.Option(
        "ws://127.0.0.1:8430/mcp",
        "--url",
        help="WebSocket URL for luxd",
    ),
) -> None:
    """Write mcp-proxy config for luxd."""
    from punt_lux.remote import MCP_PROXY_CONFIG_PATH, write_proxy_config

    write_proxy_config(url)
    print(f"Wrote {MCP_PROXY_CONFIG_PATH}")


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
