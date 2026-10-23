"""The caller scope every operation is keyed by."""

from __future__ import annotations

from dataclasses import dataclass, field

from punt_lux.domain.ids import ConnectionId

__all__ = ["Scope"]


@dataclass(frozen=True, slots=True)
class Scope:
    """The connection an operation acts on behalf of.

    For an MCP tool this is the session's ``ConnectionId``; it scopes owned
    scenes, subscriptions, and the publish sink of any element the tree installs.

    ``peer_host`` is the address the Hub observed on the transport that carried
    this contact, where a door could read one. It is a fact about the contact,
    not part of the scope's identity, so it is left out of equality and hashing:
    two scopes for one connection stay equal.
    """

    connection_id: ConnectionId
    # None = the door observed no peer (in-process library, stdio, no ASGI client).
    peer_host: str | None = field(default=None, compare=False)
