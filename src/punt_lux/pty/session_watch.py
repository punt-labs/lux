"""One watch connection to the daemon: its subscription, its list, its events."""

from __future__ import annotations

import select
import time
from collections import deque
from collections.abc import Callable
from typing import Self

from punt_lux.pty.daemon_exchange import (
    TIMEOUT_S,
    DaemonExchange,
    RetryableRefusalError,
    SessionRefusedError,
)
from punt_lux.pty.peer import Peer
from punt_lux.pty.session_listing import SessionListing
from punt_lux.wire.stream.control import ControlCodec, ControlRequest
from punt_lux.wire.stream.control_json import ControlJson
from punt_lux.wire.stream.frames import Frame, FrameError, FrameKind
from punt_lux.wire.stream.replies import FailureReply, Reply, ReplyCodec, SuccessReply
from punt_lux.wire.stream.session_events import SessionEvent, WatchRequest
from punt_lux.wire.stream.session_requests import ListRequest


class SessionWatch:
    """A connection that watches: it cannot attach, and a viewer cannot watch.

    ``open`` returns only after the daemon acknowledged the subscription, so
    a session that ends afterwards is reported as an event. Events that arrive
    while a request is pending are kept, never dropped, and ``drain`` hands
    them over in order.
    """

    _peer: Peer
    _events: deque[SessionEvent]
    _replies: deque[Reply]
    _next_id: int

    def __new__(cls, peer: Peer) -> Self:
        self = super().__new__(cls)
        self._peer = peer
        self._events, self._replies = deque(), deque()
        self._next_id = 2
        return self

    @classmethod
    def open(cls, daemon: DaemonExchange) -> Self:
        """Dial ``daemon`` on a fresh connection and subscribe to its events.

        Raises:
            OSError: The daemon is unreachable, hung up or did not answer in time.
            SessionRefusedError: The daemon refused or answered nonsense.
        """
        watch = cls(daemon.dial())
        try:
            watch._ask(WatchRequest)
        except BaseException:
            watch.close()
            raise
        return watch

    def listing(self) -> SessionListing:
        """Ask for the running sessions, on the connection that is watching.

        Raises:
            OSError: The connection was lost or the daemon did not answer.
            SessionRefusedError: The daemon refused or answered nonsense.
        """
        return SessionListing.from_result(self._ask(ListRequest).result)

    def drain(self) -> list[SessionEvent]:
        """Hand over, in arrival order, the events received so far."""
        events = list(self._events)
        self._events.clear()
        return events

    def events(self, timeout: float) -> list[SessionEvent]:
        """Wait up to ``timeout`` seconds for events; return those received.

        Raises:
            OSError: The daemon dropped this watcher or went away; reconcile.
            SessionRefusedError: The daemon sent something unreadable.
        """
        if not self._events:
            self._pump(timeout)
        return self.drain()

    def close(self) -> None:
        self._peer.close()

    def _ask(self, make: Callable[[int], ControlRequest]) -> SuccessReply:
        request = make(self._next_id)
        self._next_id += 1
        self._peer.queue(Frame(0, FrameKind.DATA, ControlCodec.encode(request)))
        deadline = time.monotonic() + TIMEOUT_S
        while not self._replies:
            if time.monotonic() >= deadline:
                raise TimeoutError("luxd-pty did not answer")
            self._pump(0.1)
        reply = self._replies.popleft()
        if isinstance(reply, FailureReply):
            refusal = RetryableRefusalError if reply.retryable else SessionRefusedError
            raise refusal(reply.error)
        return reply

    def _pump(self, timeout: float) -> None:
        writing = [self._peer.socket] if self._peer.wants_write else []
        select.select([self._peer.socket], writing, [], timeout)
        self._peer.flush()
        try:
            frames = self._peer.receive()
        except EOFError as error:
            raise ConnectionError("luxd-pty closed the watch connection") from error
        except FrameError as error:
            raise RetryableRefusalError("luxd-pty sent an unreadable frame") from error
        for frame in frames:
            self._file(frame)

    def _file(self, frame: Frame) -> None:
        try:
            fields = ControlJson.parse(frame.payload)
            if "event" in fields:
                self._events.append(SessionEvent.from_dict(fields))
            else:
                self._replies.append(ReplyCodec.decode(frame.payload))
        except ValueError as error:
            raise RetryableRefusalError(
                "luxd-pty sent an unreadable message"
            ) from error
