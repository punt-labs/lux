"""The daemon's book of sessions: who is told about them and when they go."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.pty.session_watchers import SessionWatchers
from punt_lux.wire.stream.session_events import SessionEvent

if TYPE_CHECKING:
    from punt_lux.pty.core import SessionCore
    from punt_lux.pty.peer import Peer
    from punt_lux.pty.session import TerminalSession
    from punt_lux.pty.viewers import ViewerBindings
    from punt_lux.wire.stream.new_request import NewRequest

logger = logging.getLogger(__name__)


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
        """Stop ``name``'s program now, then tell watchers and close its viewers.

        Nobody is told while the session is still held: a kill that failed before
        its IO stopped can be retried. One that failed in cleanup has stopped IO
        and left the live map, so its viewers are told even though the call fails.
        """
        held = self._core.get(name) if self._core.holds(name) else None
        try:
            self._core.kill(name)
        finally:
            if not self._core.holds(name):
                if held is not None:  # one in cleanup was announced when it left
                    self._announce(held)
                self._bindings.close_session(name, "session killed")

    def watch(self, peer: Peer) -> None:
        """Turn ``peer`` into a subscriber of created and ended events."""
        self._watchers.subscribe(peer)

    def detach(self, peer: Peer) -> None:
        """Forget ``peer`` after its connection went away."""
        self._watchers.detach(peer)

    def sweep(self) -> None:
        """Announce each finished session, remove those whose viewers were told.

        A session whose program group refuses to stop stays held and is retried
        on the next sweep; it never reaches the daemon loop.
        """
        for session in self._core.finished:
            self._announce(session)
            if not session.ended:  # a failed session sends no exit notice of its own
                self._bindings.close_session(session.name, "session failed")
            if all(b.flow.close_sent for b in self._bindings.session(session.name)):
                self._remove(session)
        self._announced &= {s.name for s in self._core.finished}
        self._watchers.drain()

    def _remove(self, session: TerminalSession) -> None:
        try:
            self._core.kill(session.name)
        except (OSError, RuntimeError):
            logger.exception("terminal %s: removal failed, will retry", session.name)

    def _announce(self, session: TerminalSession) -> None:
        if session.name not in self._announced:
            self._announced.add(session.name)
            self._watchers.publish(SessionEvent("ended", session.name, session.label))
