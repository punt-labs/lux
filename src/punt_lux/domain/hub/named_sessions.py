"""NamedSessions — the live sessions and the menu name each one holds, read as one.

Who is live and what each one is called are two halves of a single answer, and
this is the value that keeps them together. The registry builds it inside its own
critical section, from its own store, so the sessions and the names it carries
were true at one instant. Anything that reads them separately — a menu composed
from one read and labelled from another — can show a client the other read has
already retired, which is how a menu entry and a details frame come to disagree
about which client is ``lux (2)``.

Only identified sessions are named: an anonymous session contributes nothing to
the bar and takes no place in the numbering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from punt_lux.domain.hub.client_roster import ClientRoster
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.ids import ConnectionId

__all__ = ["NamedSession", "NamedSessions"]


@final
class NamedSession:
    """One live session and the name the menu calls the client that holds it."""

    _connection_id: ConnectionId
    _name: str
    _session: ClientSession
    __slots__ = ("_connection_id", "_name", "_session")

    def __new__(
        cls, connection_id: ConnectionId, name: str, session: ClientSession
    ) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        self._name = name
        self._session = session
        return self

    @property
    def connection_id(self) -> ConnectionId:
        """The connection this session holds, which a click round-trips back to."""
        return self._connection_id

    @property
    def name(self) -> str:
        """What the menu calls this client."""
        return self._name

    @property
    def callbacks(self) -> tuple[SessionCallback, ...]:
        """The commands this client registered, in registration order."""
        return self._session.callbacks


@final
class NamedSessions:
    """The sessions live at one instant, and the name each identified one holds."""

    _sessions: Mapping[ConnectionId, ClientSession]
    _names: Mapping[ConnectionId, str]
    __slots__ = ("_names", "_sessions")

    def __new__(
        cls,
        sessions: Mapping[ConnectionId, ClientSession],
        names: Mapping[ConnectionId, str],
    ) -> Self:
        self = super().__new__(cls)
        self._sessions = sessions
        self._names = names
        return self

    @classmethod
    def over(
        cls, sessions: Mapping[ConnectionId, ClientSession], roster: ClientRoster
    ) -> Self:
        """Name every identified session in *sessions* and hold the two together.

        The caller holds the registry's lock, so *sessions* is the store itself
        rather than a copy of it that some other reader has already moved past.
        """
        identities = {
            connection_id: session.identity
            for connection_id, session in sessions.items()
            if session.identity is not None
        }
        return cls(dict(sessions), roster.names_for(identities))

    @property
    def sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """The sessions that were live when this was read."""
        return self._sessions

    def name_of(self, connection_id: ConnectionId, fallback: str) -> str:
        """What the menu calls *connection_id*, or *fallback* when it holds no name.

        A connection is unnamed when it never declared an identity, or when it has
        gone since — a click can outlive the client whose entry it came from.
        """
        return self._names.get(connection_id, fallback)

    def commanding(self) -> Iterator[NamedSession]:
        """Yield each named client that registered commands, in connection order.

        A client with no commands is named but contributes no submenu: it keeps
        its number so that registering one later does not renumber the bar.
        """
        for connection_id, name in self._names.items():
            session = self._sessions[connection_id]
            if session.callbacks:
                yield NamedSession(connection_id, name, session)
