"""The state-changing MCP tools for display, menu, and frame configuration."""

from __future__ import annotations

import asyncio
from typing import Any

from punt_lux.commands import (
    Ctx as CommandCtx,
    DisplayModeOps,
    FrameOps,
    MenuOps,
    display_mode_get as display_mode_get_command,
    display_mode_set as display_mode_set_command,
    frame_close as frame_close_command,
    menu_set as menu_set_command,
)
from punt_lux.operations import DisplayModeRequest, Ok, OpError, SetMenuRequest
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import mcp

__all__ = [
    "display_mode",
    "frame_close",
    "set_display_mode",
    "set_menu",
]


@mcp.tool(name="menu_set")
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar; clicks arrive via recv().

    Each menu: {"label": "Tools", "items": [{"label": "Run", "id": "run_btn"},
    {"label": "---"}]}  — a ``"---"`` label is a separator. Hub-owned: this
    writes the Hub menu registry and the replicator pushes the bar down.
    """
    ctx: CommandCtx[MenuOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(menu_set_command(ctx, SetMenuRequest.parse(menus)))
    return signal(result)


@mcp.tool(name="frame_close")
def frame_close(frame_id: str) -> Ok | OpError:
    """Close ``frame_id``: tear down its scenes on the Hub."""
    ctx: CommandCtx[FrameOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(frame_close_command.execute(ctx, frame_id))


@mcp.tool(name="display_mode_get")
def display_mode(repo: str) -> str:
    """Read the current display mode: "display:on" or "display:off".

    ``repo`` must be the caller's absolute project path; read from
    ``<repo>/.punt-labs/lux.md``.
    """
    ctx: CommandCtx[DisplayModeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_mode_get_command(ctx, repo)).text


@mcp.tool(name="display_mode_set")
def set_display_mode(mode: str, repo: str) -> str:
    """Set the display mode to "y" (on) or "n" (off).

    ``repo`` must be the absolute path of the caller's project; the
    config is written to ``<repo>/.punt-labs/lux.md``.
    When ``y``, eagerly connects to the display server.
    """
    ctx: CommandCtx[DisplayModeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(
        display_mode_set_command(ctx, DisplayModeRequest.parse(mode, repo))
    ).text
