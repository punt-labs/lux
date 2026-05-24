"""Lux MCP server instance, lifespan, and session management."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )
    from mcp.shared.message import SessionMessage

from punt_lux.config import ConfigManager

logger = logging.getLogger(__name__)


async def _retry_eager_connect() -> None:
    """Background retries for eager display connect."""
    from punt_lux.domain.hub import client_registry

    for delay in (2.0, 5.0, 10.0):
        await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(client_registry.get)
            logger.info("Eager connect retry succeeded")
            return
        except Exception:  # noqa: BLE001
            logger.debug("Eager connect retry failed", exc_info=True)


@contextlib.asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncGenerator[None]:
    """Eager-connect to the display server when display=y.

    Runs ``client_registry.get()`` in a thread so the blocking socket
    connect and potential ``ensure_display()`` auto-spawn don't stall
    the async event loop.
    """
    from punt_lux.domain.hub import client_registry

    config_mgr = ConfigManager()
    try:
        cfg = config_mgr.read()
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read display config (%s): %s", config_mgr.path, exc)
        yield
        return

    retry_task: asyncio.Task[None] | None = None
    if cfg.display == "y":
        try:
            logger.info("display=y, eagerly connecting to display server")
            await asyncio.to_thread(client_registry.get)
        except Exception:  # noqa: BLE001 — best-effort startup
            logger.warning(
                "Eager connect failed; scheduling retries",
                exc_info=True,
            )
            retry_task = asyncio.create_task(_retry_eager_connect())
    try:
        yield
    finally:
        if retry_task is not None and not retry_task.done():
            retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry_task


mcp = FastMCP(
    "lux",
    instructions=(
        "Lux is a visual output surface. Use these tools to display "
        "text, images, buttons, separators, and interactive elements "
        "(sliders, checkboxes, combos, text inputs, radio buttons, "
        "color pickers) in a window the user can see.\n\n"
        "All lux tool output is pre-formatted plain text using unicode "
        "characters for alignment. Always emit lux output verbatim — "
        "never reformat, never convert to markdown tables, never wrap "
        "in code fences or boxes.\n\n"
        "Layout best practices:\n"
        "- Use group with layout='columns' for side-by-side elements\n"
        "- Use tab_bar to organize multi-view interfaces\n"
        "- Use collapsing_header for progressive disclosure\n"
        "- Use window for floating panels (inspector, detail views)\n"
        "- Nest containers freely: groups inside tabs, windows inside groups\n\n"
        "Common patterns:\n"
        "- Data explorer: use show_table() for filterable tables with detail\n"
        "- Dashboard: use show_dashboard() for metrics + charts + table\n"
        "- Form: input_text + combo + checkbox + button for submission\n"
        "- Custom layout: use show() to compose any element tree"
    ),
    lifespan=_lifespan,
)

# -- Per-session state for hub mode ----------------------------------------

_session_key: ContextVar[str] = ContextVar("session_key", default="local")

# Tracks menu items registered by each session for cleanup on disconnect.
_session_menus: dict[str, list[str]] = {}


def _cleanup_session(session_key: str) -> None:
    """Clean up state when a session disconnects.

    Best-effort: DisplayClient has no unregister_menu_item method, so
    menu cleanup logs and skips.  The display server handles per-client
    cleanup on disconnect anyway.
    """
    from punt_lux.domain.hub import client_registry

    with client_registry.lock:
        items = _session_menus.pop(session_key, [])
    if items:
        logger.debug(
            "Session %s disconnected; %d menu items orphaned (display handles cleanup)",
            session_key,
            len(items),
        )


async def run_mcp_session(
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
    session_key: str = "local",
) -> None:
    """Run an MCP session on the given read/write streams.

    Called by hub.py for each WebSocket connection.
    Sets ``_session_key`` ContextVar for per-session state isolation.
    """
    token = _session_key.set(session_key)
    try:
        # FastMCP private API — verify on fastmcp upgrades.
        # _lifespan_manager() must be entered before server.run() so the
        # lifespan context (eager display connect, retry tasks) is available.
        server = getattr(mcp, "_mcp_server", None)
        lifespan_mgr = getattr(mcp, "_lifespan_manager", None)
        if server is None or lifespan_mgr is None:
            msg = (
                "FastMCP._mcp_server or _lifespan_manager not found. "
                "This private API may have changed; check fastmcp version."
            )
            raise RuntimeError(msg)
        async with lifespan_mgr():
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        _session_key.reset(token)
        _cleanup_session(session_key)
