"""DetailsFrame — the frame one client's Details window lives in.

The Hub installs a client's Details scene into a frame whose name is derived
from the connection alone, and the Clients menu has to name that same frame
before any click happens so the Display can reopen it once the user has closed
it. Both sites read the name from here, so it is spelled out exactly once.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId

__all__ = ["DetailsFrame"]

_PREFIX = "lux.client-details"


@final
class DetailsFrame:
    """The Details frame of one connection, as the client names it and as stored."""

    _connection_id: ConnectionId
    __slots__ = ("_connection_id",)

    def __new__(cls, connection_id: str) -> Self:
        self = super().__new__(cls)
        self._connection_id = ConnectionId(connection_id)
        return self

    @property
    def raw_id(self) -> str:
        """The id the Details scene and frame are submitted under."""
        return f"{_PREFIX}.{self._connection_id}"

    @property
    def scoped_id(self) -> str:
        """The key the scene installer stores that frame under, owner-composed."""
        return ConnectionScopedId.compose(self._connection_id, self.raw_id)

    def presentation(self, title: str) -> ScenePresentation:
        """Place a scene in this frame, titled *title*."""
        return ScenePresentation(
            frame_id=self.raw_id,
            title=title,
            frame_title=title,
            frame_size=(560, 340),
        )
