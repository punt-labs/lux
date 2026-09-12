"""A session's menu callback, and the invocation a click on it fires.

:class:`SessionCallback` is a session's callback registration: an id it chose
plus a label. A click fires a :class:`CallbackInvocation` naming the owning
session and the callback, because the display can't infer which session a
leaf id belongs to (menu-capability-model.md). Both the leaf-id rendering and
its parse live on ``CallbackInvocation`` so the encoding has one home.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self, final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from punt_lux.domain.id_separator import ID_SEPARATOR, NONBLANK_FRAME_ID
from punt_lux.domain.ids import ConnectionId

__all__ = ["CallbackInvocation", "MenuLeaf", "MenuLeafKind", "SessionCallback"]

# The callback id luxd's own Details command carries. It opens with the
# separator, which ``SessionCallback`` refuses, so no client can register a
# callback that collides with the Hub's own — and the leaf still round-trips
# through the one leaf-id encoding, because the split takes the tag and
# connection off the front and this id is the remainder.
_DETAILS_CALLBACK_ID = f"{ID_SEPARATOR}details"

# A clicked menu leaf is one of two KINDS, and dispatch must route by the kind,
# not by guessing from whether a callback exists: an applet callback (held listen
# leg) versus an agent ``menu_set`` item (inbox notification). The two share one
# ``owner<US>local_id`` body, so a session owning both under the same local id
# (e.g. a callback "run" and a menu item "run") would be indistinguishable
# without this tag.
type MenuLeafKind = Literal["callback", "menu"]

# The wire tag each kind carries at the front of its leaf id. Kept short and
# separator-free so the tag splits cleanly off the front.
_KIND_TAG: dict[MenuLeafKind, str] = {"callback": "cb", "menu": "mi"}
_TAG_KIND: dict[str, MenuLeafKind] = {tag: kind for kind, tag in _KIND_TAG.items()}


@final
@dataclass(frozen=True, slots=True)
class MenuLeaf:
    """The kind-tagged wire id every clicked menu leaf round-trips through.

    A leaf id names its kind first, then the owning connection and the owner's
    own local id: ``<tag><US><connection><US><local_id>``. The tag is what makes
    an applet-callback leaf and an agent ``menu_set`` item leaf unambiguous even
    when a session owns both under the same local id, so dispatch routes by the
    parsed :attr:`kind` rather than by inferring it from callback existence.
    """

    kind: MenuLeafKind
    connection_id: ConnectionId
    local_id: str

    @property
    def wire_id(self) -> str:
        """Render the kind-tagged wire id a rendered leaf carries."""
        tag = _KIND_TAG[self.kind]
        return f"{tag}{ID_SEPARATOR}{self.connection_id}{ID_SEPARATOR}{self.local_id}"

    @classmethod
    def parse(cls, wire_id: str) -> Self:
        """Parse a clicked leaf id into its kind, session, and local id, or reject.

        Splits the tag and connection off the front; the local id keeps any
        remaining separators (the Hub's own Details id opens with one). An unknown
        tag, or a missing segment, never named a real stamped leaf.
        """
        parts = wire_id.split(ID_SEPARATOR, 2)
        if len(parts) != 3:
            msg = f"not a menu leaf id: {wire_id!r}"
            raise ValueError(msg)
        tag, connection, local_id = parts
        kind = _TAG_KIND.get(tag)
        if kind is None or not connection or not local_id:
            msg = f"not a menu leaf id: {wire_id!r}"
            raise ValueError(msg)
        return cls(kind, ConnectionId(connection), local_id)


class SessionCallback(BaseModel):
    """A named action a session registers so a click fires back to that session."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)  # an id-less callback is not a real state
    label: str = Field(min_length=1)  # a label-less callback is not a real state
    # absent = no owned frame (e.g. the Hub's own Details); present must be
    # non-blank and separator-free, same as ConnectionScopedId.compose.
    frame_id: str | None = Field(default=None, pattern=NONBLANK_FRAME_ID)

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
        """Render the callback-kind wire id a rendered leaf carries."""
        return MenuLeaf("callback", self.connection_id, self.callback_id).wire_id

    @classmethod
    def from_menu_id(cls, menu_id: str) -> Self:
        """Parse a clicked CALLBACK leaf id back into its session and callback.

        Rejects an agent menu-item leaf (a different kind) or a malformed id, so
        the callback path never answers an agent ``menu_set`` item.
        """
        leaf = MenuLeaf.parse(menu_id)
        if leaf.kind != "callback":
            msg = f"not a callback leaf id: {menu_id!r}"
            raise ValueError(msg)
        return cls(leaf.connection_id, leaf.local_id)
