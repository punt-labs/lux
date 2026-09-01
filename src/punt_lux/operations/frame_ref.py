"""FrameRef -- a caller's local frame name, paired with the scope that names it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.scope import Scope

__all__ = ["FrameRef"]


@final
@dataclass(frozen=True, slots=True)
class FrameRef:
    """A caller's own name for a frame, paired with the connection that owns it.

    The one identity ``raise_frame`` needs (DES-089: identity is a path, not
    a pair of loose parameters): composes the DES-086 connection-scoped store
    key deterministically, so resolution is unambiguous by construction --
    never a search across other connections' frames.
    """

    connection_id: ConnectionId
    local_id: str

    @classmethod
    def of(cls, local_id: str, *, scope: Scope) -> Self:
        """Build from a caller's local frame name and the scope naming it."""
        return cls(scope.connection_id, local_id)

    @classmethod
    def for_identity(cls, local_id: str, identity: ClientIdentity) -> Self:
        """Build from a caller's local frame name and its own declared identity."""
        return cls(identity.connection_id, local_id)

    def scoped(self) -> str:
        """Return the connection-scoped store key this ref composes to."""
        return ConnectionScopedId.compose(self.connection_id, self.local_id)
