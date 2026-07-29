"""Owner — who installed an element: its connection and the identity it declared."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.ownership_error import HubOwnershipError

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["Owner"]


@dataclass(frozen=True, slots=True)
class Owner:
    """Who installed an element: the wire connection and the identity it declared.

    ``connection_id`` is the enforcement and cleanup key — ownership checks and the
    disconnect walk compare it. ``identity`` is the attribution introspection reads;
    it is ``None`` for a caller that installed without declaring one, and it is
    captured at install so it survives the connection that installed it.
    """

    connection_id: ConnectionId
    identity: ClientIdentity | None = None

    @classmethod
    def from_session(
        cls, connection_id: ConnectionId, session: ClientSession | None
    ) -> Self:
        """Mint an owner, taking the identity from the session if it declared one."""
        return cls(connection_id, session.identity if session is not None else None)

    def owned_by(self, connection_id: ConnectionId) -> bool:
        """Whether this owner is the given connection — the enforcement check."""
        return self.connection_id == connection_id

    def ensure_owned_by(
        self, attempting: ConnectionId, scene_id: SceneId, element_id: ElementId
    ) -> None:
        """Raise ``HubOwnershipError`` unless ``attempting`` is this owner."""
        if self.connection_id != attempting:
            raise HubOwnershipError(
                scene_id=scene_id,
                element_id=element_id,
                attempting=attempting,
                owning=self.connection_id,
            )
