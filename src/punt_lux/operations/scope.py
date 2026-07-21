"""The caller scope every operation is keyed by."""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.ids import ConnectionId

__all__ = ["Scope"]


@dataclass(frozen=True, slots=True)
class Scope:
    """The connection an operation acts on behalf of.

    For an MCP tool this is the session's ``ConnectionId``; it scopes owned
    scenes, subscriptions, and the publish sink of any element the tree installs.
    """

    connection_id: ConnectionId
