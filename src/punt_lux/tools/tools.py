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

from punt_lux.domain.hub import client_registry, hub, hub_display
from punt_lux.domain.hub.details_instance import hub_client_details
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.replicator_instance import (
    hub_callback_router,
    hub_menu_registry,
    hub_replicator,
)
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import (
    DisplayModeState,
    Operations,
    OpError,
    SceneShown,
    Scope,
)
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.ports import HubPorts
from punt_lux.paths import DisplayPaths
from punt_lux.tools.server import _session_key

# The package-internal interface the sibling tool modules reach through ``_core``:
# the one facade and the result formatters. Underscore-named because they are not
# the MCP public surface, listed here because they are used across the package.
__all__ = [
    "OPERATIONS",
    "_fault_or",
    "_format_display_mode",
    "_format_render",
    "_format_update",
    "_scope",
]


def _hub_ports() -> HubPorts:
    """Bundle the Hub collaborators (element decode, inbox, display) for operations."""
    return HubPorts(
        element_factory=hub_element_factory,
        ensure_writer=ensure_writer,
        next_event=next_event,
        display_port=_display_connection(),
    )


def _display_connection() -> HubDisplayConnection:
    """Build luxd's one bounded connection to the display for proxied ops."""
    return HubDisplayConnection(
        is_running=lambda: DisplayPaths().is_running(),
        clients=client_registry,
    )


def _build_operations() -> Operations:
    """Compose the operations facade — the presentation-layer composition root.

    Every collaborator is injected here; nothing under ``operations/`` binds a
    process singleton or reaches back into ``tools/`` at import time.
    """
    return Operations.for_store(
        hub_display,
        hub_replicator,
        hub=hub,
        client_registry=client_registry,
        menu_registry=hub_menu_registry,
        callback_router=hub_callback_router,
        ports=_hub_ports(),
    )


# The process-wide operations facade, built once at the composition root.
OPERATIONS = _build_operations()

# The Hub's own Details command runs on this facade. The click arrives in the
# domain-layer interaction dispatch, which may not call operations, so the
# binding is made here where the process is wired.
hub_client_details.bind(OPERATIONS)


def _connection_id() -> ConnectionId:
    """Return the calling MCP session's ``ConnectionId``."""
    return ConnectionId(_session_key.get())


def _scope() -> Scope:
    """Resolve the calling MCP session's operation scope."""
    return Scope(_connection_id())


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
