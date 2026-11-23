"""Lux MCP server instance and per-session identity.

The ``mcp`` FastMCP instance is the tool registry; ``_session_key`` carries the
calling session's identity so each tool resolves its Hub scope. luxd's transport
leg (:mod:`punt_lux.hub.mcp_transport`) binds the initialized session's key for
each call; absent that binding it stays at the default.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from punt_lux.kernel.client_host import UNOBSERVED
from punt_lux.tools.session_binding import SessionBinding

if TYPE_CHECKING:
    from punt_lux.kernel.client_host import ClientHost

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


# The host the transport observed at session initialization. Unobserved
# on stdio and in-process calls, which have no peer; the row then reads "unknown".
_client_host: ContextVar[ClientHost] = ContextVar("client_host", default=UNOBSERVED)


def bind_session(session_key: str, client_host: ClientHost) -> SessionBinding:
    """Bind the calling context to an MCP session; return the binding to release.

    The transport carries the identity and observed peer to every tool.
    Release both together with :func:`unbind_session`.
    """
    return SessionBinding(_session_key.set(session_key), _client_host.set(client_host))


def unbind_session(binding: SessionBinding) -> None:
    """Release a session binding created by :func:`bind_session`."""
    binding.release()


def current_session() -> str:
    """Return the MCP session identity bound to the current context."""
    return _session_key.get()


def current_client_host() -> ClientHost:
    """Return the session's observed peer address, if any."""
    return _client_host.get()
