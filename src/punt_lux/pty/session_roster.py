"""The daemon's book of sessions: who is told about them and when they go."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.pty.finish_deadlines import FinishDeadlines
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
    Removal never waits for a watcher. A viewer that has not taken the session's
    last output within the grace period loses what it has not been sent and is
    sent CLOSE, so a stalled viewer cannot keep a finished session forever.
    """

    _core: SessionCore
    _bindings: ViewerBindings
    _watchers: SessionWatchers
    _announced: set[str]
    _deadlines: FinishDeadlines

    def __new__(
        cls,
        core: SessionCore,
        bindings: ViewerBindings,
        deadlines: FinishDeadlines | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        self._watchers = SessionWatchers()
        self._announced = set()
        self._deadlines = deadlines or FinishDeadlines()
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
        """Turn ``peer`` into a subscriber of created and ended events.

        A watcher that falls behind is closed with its connection, so a
        connection that carries viewers never watches: it would end them too.

        Raises:
            ValueError: ``peer`` has viewers, or is already watching.
        """
        if any(binding.peer is peer for binding in self._bindings.all):
            raise ValueError("a connection with viewers cannot watch; dial another")
        self._watchers.subscribe(peer)

    def require_not_watching(self, peer: Peer) -> None:
        """Refuse a viewer on a watching connection, for the same reason.

        Raises:
            ValueError: ``peer`` is watching.
        """
        if peer in self._watchers:
            raise ValueError("a watching connection cannot attach; dial another")

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
            if self._deadlines.overdue(session.name):
                self._abandon_stalled(session)
            if all(b.flow.close_sent for b in self._bindings.session(session.name)):
                self._remove(session)
        names = {s.name for s in self._core.finished}
        self._announced &= names
        self._deadlines.keep_only(names)
        self._watchers.drain()

    def _abandon_stalled(self, session: TerminalSession) -> None:
        for binding in self._bindings.session(session.name):
            if not binding.flow.close_sent:
                logger.warning(
                    "terminal %s: viewer on channel %d took no output, dropping it",
                    session.name,
                    binding.channel,
                )
                binding.flow.abandon_unsent()

    def _remove(self, session: TerminalSession) -> None:
        try:
            self._core.kill(session.name)
        except (OSError, RuntimeError):
            logger.exception("terminal %s: removal failed, will retry", session.name)

    def _announce(self, session: TerminalSession) -> None:
        if session.name not in self._announced:
            self._announced.add(session.name)
            self._watchers.publish(SessionEvent("ended", session.name, session.label))
