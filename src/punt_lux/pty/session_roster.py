"""The daemon's book of sessions: who is told about them and when they go."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.session_watchers import SessionWatchers
from punt_lux.wire.stream.session_events import SessionEvent

if TYPE_CHECKING:
    from punt_lux.pty.core import SessionCore
    from punt_lux.pty.peer import Peer
    from punt_lux.pty.session import TerminalSession
    from punt_lux.pty.viewers import ViewerBindings
    from punt_lux.wire.stream.new_request import NewRequest


class SessionRoster:
    """Create, list and end sessions, and tell watchers each time.

    A finished session is removed once CLOSE has been sent to each of its
    viewers, so none is left showing a live screen for a shell that is gone.
    Removal never waits for a watcher.
    """

    _core: SessionCore
    _bindings: ViewerBindings
    _watchers: SessionWatchers
    _announced: set[str]

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        self._watchers = SessionWatchers()
        self._announced = set()
        return self

    def create(self, request: NewRequest) -> TerminalSession:
        """Start a session and tell watchers it exists."""
        session = self._core.create(request)
        self._watchers.publish(SessionEvent("created", session.name, session.label))
        return session

    def describe(self) -> list[dict[str, object]]:
        """List every session the daemon holds."""
        return self._core.describe()

    def kill(self, name: str) -> None:
        """End ``name`` now: tell watchers, close its viewers, stop its program."""
        if self._core.holds(name):  # one in cleanup was announced when it left
            self._announce(self._core.get(name))
        self._bindings.close_session(name, "session killed")
        self._core.kill(name)

    def watch(self, peer: Peer) -> None:
        """Turn ``peer`` into a subscriber of created and ended events."""
        self._watchers.subscribe(peer)

    def detach(self, peer: Peer) -> None:
        """Forget ``peer`` after its connection went away."""
        self._watchers.detach(peer)

    def sweep(self) -> None:
        """Announce each finished session, remove those whose viewers were told."""
        for session in self._core.finished:
            self._announce(session)
            if all(b.flow.close_sent for b in self._bindings.session(session.name)):
                self._core.kill(session.name)
        self._announced &= {s.name for s in self._core.finished}
        self._watchers.drain()

    def _announce(self, session: TerminalSession) -> None:
        if session.name not in self._announced:
            self._announced.add(session.name)
            self._watchers.publish(SessionEvent("ended", session.name, session.label))
