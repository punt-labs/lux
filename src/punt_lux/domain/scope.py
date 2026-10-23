"""The caller scope every operation is keyed by."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from punt_lux.client_host import UNOBSERVED, ClientHost
from punt_lux.domain.ids import ConnectionId

__all__ = ["Scope"]


@dataclass(frozen=True, slots=True)
class Scope:
    """The connection an operation acts on behalf of.

    For an MCP tool this is the session's ``ConnectionId``; it scopes owned
    scenes, subscriptions, and the publish sink of any element the tree installs.

    ``client_host`` is the address the Hub observed on the transport that carried
    this contact, where a door could read one. It is a fact about the contact,
    not part of the scope's identity, so it is left out of equality and hashing:
    two scopes for one connection stay equal.

    ``is_contact`` says whether the caller itself reached the Hub. A Hub-internal
    act under an owner's name (its Details scene, a root the owner forgot) is not
    the owner's contact, so it never renews the owner's lease.
    """

    connection_id: ConnectionId
    # UNOBSERVED = the door saw no peer (in-process library, stdio, no ASGI client).
    client_host: ClientHost = field(default=UNOBSERVED, compare=False)
    is_contact: bool = field(default=True, compare=False)

    @classmethod
    def observed(cls, connection_id: ConnectionId, client_host: ClientHost) -> Self:
        """The scope of a contact whose transport reported where it came from."""
        return cls(connection_id, client_host)

    @classmethod
    def on_behalf_of(cls, owner: ConnectionId) -> Self:
        """The scope of a Hub-internal act under ``owner``'s name: no contact."""
        return cls(owner, is_contact=False)

    @classmethod
    def in_process(cls, connection_id: ConnectionId) -> Self:
        """The scope of a caller no transport observed: a library or stdio client."""
        return cls(connection_id)
