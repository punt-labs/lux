"""Lux MCP server — expose display tools to AI agents.

Provides FastMCP tools: ``show``, ``update``, ``clear``, ``ping``,
and ``recv``.
Uses :class:`LuxClient` under the hood with lazy connection on first call.

Run via stdio transport::

    lux serve
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastmcp import FastMCP

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    InteractionMessage,
    Patch,
    element_from_dict,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "lux",
    instructions=(
        "Lux is a visual output surface. Use these tools to display "
        "text, images, buttons, separators, and interactive elements "
        "(sliders, checkboxes, combos, text inputs, radio buttons, "
        "color pickers) in a window the user can see."
    ),
)

_client: LuxClient | None = None


def _get_client() -> LuxClient:
    """Return a connected LuxClient, creating one if needed."""
    global _client
    if _client is None or not _client.is_connected:
        _client = LuxClient()
        _client.connect()
    return _client


@mcp.tool()
def show(
    scene_id: str,
    elements: list[dict[str, Any]],
    title: str | None = None,
    layout: str = "single",
) -> str:
    """Display a scene in the Lux window.

    Replaces the current window contents with the given elements.
    Each element is a dict with a ``kind`` field.

    Display elements:
      Text:         {"kind": "text", "id": "t1", "content": "Hello", "style": "heading"}
      Button:       {"kind": "button", "id": "b1", "label": "Click me"}
      Image:        {"kind": "image", "id": "i1", "path": "/path/to/img.png"}
      Separator:    {"kind": "separator"}

    Interactive elements (generate "changed" events via recv):
      Slider:       {"kind": "slider", "id": "sl1", "label": "Vol"}
      Checkbox:     {"kind": "checkbox", "id": "cb1", "label": "On"}
      Combo:        {"kind": "combo", "id": "co1", "items": ["A","B"]}
      Input text:   {"kind": "input_text", "id": "it1", "label": "Name"}
      Radio:        {"kind": "radio", "id": "r1", "items": ["A","B"]}
      Color picker: {"kind": "color_picker", "id": "cp1", "label": "Bg"}

    Returns ``"ack:<scene_id>"`` on success or ``"timeout"`` if the
    display doesn't respond.
    """
    client = _get_client()
    typed_elements = [element_from_dict(e) for e in elements]
    ack = client.show(scene_id, typed_elements, title=title, layout=layout)
    if ack is None:
        return "timeout"
    return f"ack:{ack.scene_id}"


@mcp.tool()
def update(
    scene_id: str,
    patches: list[dict[str, Any]],
) -> str:
    """Update elements in the current scene without replacing everything.

    Each patch targets an element by id and can set fields or remove it:
      {"id": "t1", "set": {"content": "Updated text"}}
      {"id": "b1", "remove": True}

    Returns ``"ack:<scene_id>"`` on success or ``"timeout"`` if the
    display doesn't respond.
    """
    client = _get_client()
    typed_patches = [
        Patch(
            id=p["id"],
            set=p.get("set"),
            remove=p.get("remove", False),
            insert_after=p.get("insert_after"),
        )
        for p in patches
    ]
    ack = client.update(scene_id, typed_patches)
    if ack is None:
        return "timeout"
    return f"ack:{ack.scene_id}"


@mcp.tool()
def clear() -> str:
    """Clear the Lux display window. Removes all content."""
    client = _get_client()
    client.clear()
    return "cleared"


@mcp.tool()
def ping() -> str:
    """Ping the display server. Returns round-trip time or "timeout"."""
    client = _get_client()
    pong = client.ping()
    if pong is None:
        return "timeout"
    if pong.ts is not None:
        rtt = time.time() - pong.ts
        return f"pong:rtt={rtt:.3f}s"
    return "pong"


@mcp.tool()
def recv(timeout: float = 1.0) -> str:
    """Receive the next event from the display (e.g., button clicks).

    Returns a description of the event or "none" if no event within timeout.
    """
    client = _get_client()
    msg = client.recv(timeout=timeout)
    if msg is None:
        return "none"
    if isinstance(msg, InteractionMessage):
        return (
            f"interaction:element={msg.element_id},"
            f"action={msg.action},value={msg.value}"
        )
    return f"event:{type(msg).__name__}"
