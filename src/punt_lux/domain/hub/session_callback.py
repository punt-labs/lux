"""A session's menu callback, and the invocation a click on it fires.

:class:`SessionCallback` is a session's callback registration: an id it chose
plus a label. A click fires a :class:`CallbackInvocation` naming the owning
session and the callback, because the display can't infer which session a
leaf id belongs to (menu-capability-model.md). Both the leaf-id rendering and
its parse live on ``CallbackInvocation`` so the encoding has one home.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from punt_lux.domain.hub.id_separator import ID_SEPARATOR
from punt_lux.domain.ids import ConnectionId

__all__ = ["CallbackInvocation", "SessionCallback"]

# The callback id luxd's own Details command carries. It opens with the
# separator, which ``SessionCallback`` refuses, so no client can register a
# callback that collides with the Hub's own — and the leaf still round-trips
# through the one leaf-id encoding, because the join splits on the first
# separator and this id is the remainder.
_DETAILS_CALLBACK_ID = f"{ID_SEPARATOR}details"

# Mirrors ConnectionScopedId.compose's non-blank, separator-free rule (regex,
# not lookahead -- unsupported by pydantic-core) so a bad id fails here.
_NONBLANK_FRAME_ID = rf"^[^{ID_SEPARATOR}]*[^{ID_SEPARATOR}\s][^{ID_SEPARATOR}]*$"


class SessionCallback(BaseModel):
    """A named action a session registers so a click fires back to that session."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)  # an id-less callback is not a real state
    label: str = Field(min_length=1)  # a label-less callback is not a real state
    # absent = no owned frame (e.g. the Hub's own Details); present must be
    # non-blank and separator-free, same as ConnectionScopedId.compose.
    frame_id: str | None = Field(default=None, pattern=_NONBLANK_FRAME_ID)

    @field_validator("id")
    @classmethod
    def _reject_separator(cls, value: str) -> str:
        """Reject an id carrying the leaf-id separator.

        It would split ambiguously in the composite leaf id at dispatch.
        """
        if ID_SEPARATOR in value:
            msg = "callback id must not contain the unit separator"
            raise ValueError(msg)
        return value


@final
@dataclass(frozen=True, slots=True)
class CallbackInvocation:
    """The session-and-callback a menu click fires, and the leaf id it round-trips.

    The Hub routes by ``connection_id``; the display never infers the session
    from who clicked, since there is no "who" at the screen.
    """

    connection_id: ConnectionId
    callback_id: str

    @classmethod
    def details(cls, connection_id: ConnectionId) -> Self:
        """The invocation the Hub's own Details command on *connection_id* fires.

        Every submenu carries this command; the Hub answers it itself,
        reporting that connection's own state rather than routing to a session.
        """
        return cls(connection_id, _DETAILS_CALLBACK_ID)

    @property
    def is_details(self) -> bool:
        """Whether this invocation is the Hub's own Details command."""
        return self.callback_id == _DETAILS_CALLBACK_ID

    @property
    def menu_id(self) -> str:
        """Render the wire id a rendered leaf carries so a click round-trips here."""
        return f"{self.connection_id}{ID_SEPARATOR}{self.callback_id}"

    @classmethod
    def from_menu_id(cls, menu_id: str) -> Self:
        """Parse a clicked leaf id back into its session and callback, or reject it.

        A leaf id joins connection and callback on the unit separator; one
        lacking the separator or an empty segment never named a real leaf.
        """
        connection, separator, callback = menu_id.partition(ID_SEPARATOR)
        if not separator or not connection or not callback:
            msg = f"not a callback leaf id: {menu_id!r}"
            raise ValueError(msg)
        return cls(ConnectionId(connection), callback)
