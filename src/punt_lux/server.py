"""Lux MCP server — expose display tools to AI agents.

Provides FastMCP tools: ``show``, ``update``, ``clear``, and ``ping``.
Uses :class:`LuxClient` under the hood with lazy connection on first call.

Run via stdio transport::

    lux serve
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    ButtonElement,
    ImageElement,
    InteractionMessage,
    Patch,
    SeparatorElement,
    TextElement,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "lux",
    instructions=(
        "Lux is a visual output surface. Use these tools to display "
        "text, images, buttons, and separators in a window the user can see."
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


def _build_element(
    elem: dict[str, Any],
) -> TextElement | ButtonElement | ImageElement | SeparatorElement:
    """Convert a raw dict to a typed Element."""
    kind = elem.get("kind", "text")
    if kind == "text":
        return TextElement(
            id=elem["id"],
            content=elem.get("content", ""),
            style=elem.get("style"),
        )
    if kind == "button":
        return ButtonElement(
            id=elem["id"],
            label=elem.get("label", ""),
            action=elem.get("action"),
            disabled=elem.get("disabled", False),
        )
    if kind == "image":
        return ImageElement(
            id=elem["id"],
            path=elem.get("path"),
            data=elem.get("data"),
            format=elem.get("format"),
            alt=elem.get("alt"),
            width=elem.get("width"),
            height=elem.get("height"),
        )
    if kind == "separator":
        return SeparatorElement(id=elem.get("id"))
    msg = f"Unknown element kind: {kind}"
    raise ValueError(msg)


@mcp.tool()
def show(
    scene_id: str,
    elements: list[dict[str, Any]],
    title: str | None = None,
    layout: str = "single",
) -> str:
    """Display a scene in the Lux window.

    Replaces the current window contents with the given elements.
    Each element is a dict with a "kind" field: "text", "button",
    "image", or "separator".

    Text element:   {"kind": "text", "id": "t1", "content": "Hello", "style": "heading"}
    Button element: {"kind": "button", "id": "b1", "label": "Click me"}
    Image element:  {"kind": "image", "id": "i1", "path": "/path/to/img.png"}
    Separator:      {"kind": "separator"}

    Returns "ack" on success or "timeout" if the display doesn't respond.
    """
    client = _get_client()
    typed_elements = [_build_element(e) for e in elements]
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
      {"id": "b1", "remove": true}

    Returns "ack" on success or "timeout" if the display doesn't respond.
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
    if pong.ts is not None and pong.display_ts is not None:
        rtt = pong.display_ts - pong.ts
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
