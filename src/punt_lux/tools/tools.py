"""The MCP tool composition root and the shared result formatters.

This module builds the one process-wide :data:`OPERATIONS` facade every tool
calls and holds the small formatters that turn an operation result into a tool's
status line. The tools themselves live beside it: read-only introspection and
getters in ``read_tools``, state changes in ``write_tools``, the ``show``
conveniences in ``composite_tools``, and Agent Subscribe / Publish in
``subscribe_tools``. Those modules reach ``OPERATIONS`` and these formatters
through ``_core`` at call time, so the characterization corpus can rebind
``OPERATIONS`` to an isolated store.
"""

from __future__ import annotations

from collections.abc import Callable

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import ConnectionId
from punt_lux.hub_composition import HubComposition
from punt_lux.operations import (
    DisplayModeState,
    OpError,
    SceneShown,
    Scope,
)
from punt_lux.tools.server import _session_key

__all__ = [
    "OPERATIONS",
    "_fault_or",
    "_format_display_mode",
    "_format_render",
    "_format_update",
    "_identity",
    "_scope",
]


# The process-wide operations facade, built once from the one wiring recipe.
OPERATIONS = HubComposition.operations()

# The Hub answers its own Details clicks; the recipe binds the renderer they run.
HubComposition.bind_client_details()


def _connection_id() -> ConnectionId:
    """Return the calling MCP session's ``ConnectionId``."""
    return ConnectionId(_session_key.get())


def _scope() -> Scope:
    """Resolve the calling MCP session's operation scope."""
    return Scope(_connection_id())


def _identity() -> ClientIdentity:
    """Resolve the calling MCP session's identity for the commands layer's Ctx.

    A session that has already called ``identify`` gets that declaration back.
    One that has not yet declared itself is a real, honest state (DES-057) --
    it resolves to an ``mcp-session`` identity named after its own connection,
    distinct from every other session's, rather than a shared stand-in that
    would collapse every unidentified caller into one bucket.
    """
    scope = _scope()
    declared = OPERATIONS.identity_of(scope=scope)
    if declared is not None:
        return declared
    return ClientIdentity(kind="mcp-session", name=f"mcp:{scope.connection_id}")


def _format_render(result: SceneShown | OpError) -> str:
    """Render a ``render``/``render_table``/``render_dashboard`` result.

    A parse-level ``invalid_request`` carries the specific legacy message with no
    prefix; every other rejection (submission gate, undecodable element) is a
    ``"scene not rendered — "`` error.
    """
    if isinstance(result, SceneShown):
        return f"shown:{result.scene_id}"
    if result.code == "invalid_request":
        return f"error: {result.reason}"
    return f"error: scene not rendered — {result.reason}"


def _format_update(result: SceneShown | OpError) -> str:
    """Render an ``update`` result as its legacy status line."""
    if isinstance(result, SceneShown):
        return f"shown:{result.scene_id}"
    return f"error: scene not updated — {result.reason}"


def _format_display_mode(result: DisplayModeState | OpError) -> str:
    """Render a display-mode result, reproducing the legacy ValueError on error.

    The operation never raises; the MCP tools historically raised ``ValueError``
    for a bad mode or repo, so the adapter re-raises with the same message.
    """
    if isinstance(result, OpError):
        raise ValueError(result.reason)
    return f"display:{result.mode}"


def _fault_line(err: OpError) -> str:
    """Render a proxied operation's ``OpError`` as its legacy status line.

    A display that is not running reads ``"not running"`` and a bounded round-trip
    that elapsed reads ``"timeout"``, matching the two short-circuits the display
    tools returned before; every other cause reads ``"error: <reason>"``.
    """
    if err.code == "display_unavailable":
        return "not running"
    if err.code == "timeout":
        return "timeout"
    return f"error: {err.reason}"


def _fault_or[T](result: T | OpError, render: Callable[[T], str]) -> str:
    """Render ``result`` with ``render``, or as its fault line when it is an error."""
    return _fault_line(result) if isinstance(result, OpError) else render(result)
