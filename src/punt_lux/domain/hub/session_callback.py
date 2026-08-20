"""A session's menu callback, and the invocation a click on it fires.

A menu item is a callback a session registers: an id the session chose and a
label the user reads. :class:`SessionCallback` is that registration. A click on
the rendered leaf fires a :class:`CallbackInvocation` — the owning session and
the callback within it — which the Hub routes back to that session.

The menu leaf carries one wire id, but a click must name both the session and the
callback, because the display cannot know which of many sessions a click belongs
to (menu-capability-model.md). ``CallbackInvocation`` owns that composite id: it
renders the leaf id a session's callback gets and parses a clicked leaf id back
into the session-and-callback pair. The two live on one class so the encoding has
a single home.
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


class SessionCallback(BaseModel):
    """A named action a session registers so a click fires back to that session."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)  # an id-less callback is not a real state
    label: str = Field(min_length=1)  # a label-less callback is not a real state

    @field_validator("id")
    @classmethod
    def _reject_separator(cls, value: str) -> str:
        """Reject an id carrying the leaf-id separator so the wire id round-trips.

        The composite menu-leaf id joins the connection and this id on the unit
        separator; an id that itself carried the separator would split ambiguously
        at dispatch, so it is malformed at registration, not silently accepted.
        """
        if ID_SEPARATOR in value:
            msg = "callback id must not contain the unit separator"
            raise ValueError(msg)
        return value


@final
@dataclass(frozen=True, slots=True)
class CallbackInvocation:
    """The session-and-callback a menu click fires, and the leaf id it round-trips.

    ``connection_id`` names the owning session and ``callback_id`` the callback
    within it. The Hub routes the invocation to that session; the display never
    infers the session from who clicked, because at the screen there is no "who".
    """

    connection_id: ConnectionId
    callback_id: str

    @classmethod
    def details(cls, connection_id: ConnectionId) -> Self:
        """The invocation the Hub's own Details command on *connection_id* fires.

        Every client's submenu carries this command, and the Hub answers it
        itself rather than routing it: it renders the state of that connection,
        which is the Hub's own to report.
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

        A leaf id is the connection and callback joined on the unit separator; an
        id lacking the separator, or with an empty connection or callback segment,
        never named a callback leaf and is rejected rather than routed to a
        nonexistent session or callback.
        """
        connection, separator, callback = menu_id.partition(ID_SEPARATOR)
        if not separator or not connection or not callback:
            msg = f"not a callback leaf id: {menu_id!r}"
            raise ValueError(msg)
        return cls(ConnectionId(connection), callback)
