"""Lux MCP server instance and per-session identity.

The ``mcp`` FastMCP instance is the tool registry; ``_session_key`` carries the
calling session's identity so each tool resolves its Hub scope. luxd's transport
leg (:mod:`punt_lux.mcp_transport`) sets ``_session_key`` per session before the
session's task is spawned; absent that binding it stays at the default.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


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
)

# Per-session identity for hub mode; the stdio path leaves it at "local".
_session_key: ContextVar[str] = ContextVar("session_key", default="local")


def bind_session(session_key: str) -> Token[str]:
    """Bind the calling context to an MCP session identity; return the reset token.

    luxd's transport leg binds a session before the SDK spawns its task, so the
    copied task context carries the identity to every tool and the cleanup
    cascade. The returned token releases the binding via :func:`unbind_session`.
    """
    return _session_key.set(session_key)


def unbind_session(token: Token[str]) -> None:
    """Release a session binding created by :func:`bind_session`."""
    _session_key.reset(token)


def current_session() -> str:
    """The MCP session identity bound to the calling context."""
    return _session_key.get()
