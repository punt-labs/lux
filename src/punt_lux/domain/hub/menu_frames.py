"""MenuFrames — the frames the menu items of one connection open.

A menu item names its frame before any click, because the Display reopens a
closed frame on its own and only the Hub knows which frame an item belongs to.
Applet commands and the Hub's own Details command are named the same way here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.details_frame import DetailsFrame

if TYPE_CHECKING:
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.ids import ConnectionId

__all__ = ["MenuFrames"]


@final
class MenuFrames:
    """The store keys of the frames one connection's menu items open."""

    _connection_id: ConnectionId
    __slots__ = ("_connection_id",)

    def __new__(cls, connection_id: ConnectionId) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        return self

    @property
    def details(self) -> str:
        """The frame the Hub's own Details command opens."""
        return DetailsFrame(self._connection_id).scoped_id

    def of(self, callback: SessionCallback) -> str | None:
        """The frame *callback* opens; None when it registered no frame."""
        if callback.frame_id is None:
            return None
        return ConnectionScopedId.compose(self._connection_id, callback.frame_id)
