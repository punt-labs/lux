"""The caller scope every operation is keyed by."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Self

from punt_lux.client_host import UNOBSERVED, ClientHost
from punt_lux.domain.ids import ConnectionId

__all__ = ["Provenance", "Scope"]

# Where a scope came from, which settles both what host it carries and whether
# acting under it is the connection reaching the Hub. ``observed``: a transport
# reported the peer. ``in_process``: a caller no transport observed (library,
# stdio). ``on_behalf_of``: the Hub acting under an owner's name. ``client_side``:
# the key a remote client names its own requests under; the Hub reads the real
# scope from the transport.
Provenance = Literal["observed", "in_process", "on_behalf_of", "client_side"]


@dataclass(frozen=True, slots=True)
class Scope:
    """The connection an operation acts on behalf of.

    For an MCP tool this is the session's ``ConnectionId``; it scopes owned
    scenes, subscriptions, and the publish sink of any element the tree installs.

    ``client_host`` and ``provenance`` are facts about the contact, not part of
    the scope's identity, so they are left out of equality and hashing: two scopes
    for one connection stay equal. Build one through a named constructor, which
    says where it came from.
    """

    connection_id: ConnectionId
    client_host: ClientHost = field(compare=False)
    provenance: Provenance = field(compare=False)

    def __post_init__(self) -> None:
        if (self.provenance == "observed") != self.client_host.observed:
            msg = (
                f"a {self.provenance!r} scope cannot carry host "
                f"{self.client_host!r}: only an observed scope has one"
            )
            raise ValueError(msg)

    @classmethod
    def observed(cls, connection_id: ConnectionId, client_host: ClientHost) -> Self:
        """The scope of a contact whose transport reported where it came from.

        A transport that reported no peer is an in-process caller, whatever the
        door called it.
        """
        if not client_host.observed:
            return cls.in_process(connection_id)
        return cls(connection_id, client_host, "observed")

    @classmethod
    def in_process(cls, connection_id: ConnectionId) -> Self:
        """The scope of a caller no transport observed: a library or stdio client."""
        return cls(connection_id, UNOBSERVED, "in_process")

    @classmethod
    def on_behalf_of(cls, owner: ConnectionId) -> Self:
        """The scope of a Hub-internal act under ``owner``'s name: no contact."""
        return cls(owner, UNOBSERVED, "on_behalf_of")

    @classmethod
    def client_side(cls, connection_id: ConnectionId) -> Self:
        """The key a remote client names its own requests under; never a contact."""
        return cls(connection_id, UNOBSERVED, "client_side")

    @property
    def is_contact(self) -> bool:
        """Whether the connection itself reached the Hub through this scope."""
        return self.provenance in ("observed", "in_process")
