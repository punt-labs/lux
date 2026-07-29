"""SceneOwner — the identity-bearing read shape for who owns a root in a scene."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict

from punt_lux.domain.hub.client_identity import ClientIdentity

if TYPE_CHECKING:
    from punt_lux.domain.hub.owner import Owner

__all__ = ["SceneOwner"]


class SceneOwner(BaseModel):
    """One owner of a root in a scene: its connection and the identity it declared.

    ``identity`` is the structured attribution — kind, name, repository, agent —
    when the owner declared one; ``None`` leaves the ``connection_id`` as the only
    handle, the honest answer for a caller that has not identified.
    """

    model_config = ConfigDict(frozen=True)

    connection_id: str
    identity: ClientIdentity | None = None

    @classmethod
    def of(cls, owner: Owner) -> Self:
        """Build the read shape from a Hub-side :class:`Owner` record."""
        return cls(connection_id=str(owner.connection_id), identity=owner.identity)
