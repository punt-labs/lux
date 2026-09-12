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
    frame_remove as frame_remove_command,
    menu_set as menu_set_command,
)
from punt_lux.commands._frame_remove_request import FrameRemoveRequest
from punt_lux.operations import Ok, OpError, SetMenuRequest
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import mcp

__all__ = ["display_mode", "frame_remove", "set_menu"]


@mcp.tool(name="menu_set")
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar; clicks arrive via recv().

    Each menu: {"label": "Tools", "items": [{"label": "Run", "id": "run_btn",
    "frame_id": "dash"}, {"label": "---"}]} — a ``"---"`` label is a separator.
    An item's optional ``frame_id`` names a frame the item raises on click (a
    frame you created with ``show(..., frame_id=...)``); it raises that frame AND
    reports the click. On click, a ``{"menu": ..., "item": "<id>"}`` event lands
    on your inbox — drain it with ``recv()``, no ``topic_subscribe`` needed. The
    bar is owned by this session, so identify first; two sessions' bars never
    clobber, and yours leaves the display when the session ends.
    """
    ctx: CommandCtx[MenuOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(
        menu_set_command(ctx, SetMenuRequest.parse(menus), scope=_core._scope())
    )
    return signal(result)


@mcp.tool(name="frame_remove")
def frame_remove(frame_id: str) -> Ok | OpError:
    """Remove the caller's own ``frame_id``: tear down its scenes on the Hub.

    A foreign, missing, or malformed id is a named error, never a false success.
    """
    ctx: CommandCtx[FrameOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    request = FrameRemoveRequest(ctx, frame_id, _core._scope())
    return asyncio.run(frame_remove_command.execute(request))


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
