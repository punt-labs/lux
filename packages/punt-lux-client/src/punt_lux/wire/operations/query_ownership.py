"""SceneOwner — the identity-bearing read shape for who owns a root in a scene."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from punt_lux.wire.model.client_identity import ClientIdentity

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
