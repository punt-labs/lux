"""ClientCalls — the Hub's table of requests pending on a provider's listen leg.

A caller enters a request for one listen session, the session's writer sends the
request frame, and the caller blocks until one outcome: a reply, a refusal, the
deadline, or the loss of the session. The rules (DES-107, decision 3):

- A call leaves ``pending`` once, so its waiter sees one outcome.
- A reply or refusal counts only from the session the request went to.
- An outcome removes the entry; a later frame for it is dropped.
- A session's end resolves every call pending on it as lost, in the same step.
  Nothing is redelivered to a successor: a replayed ``kill`` or ``new`` would be a
  second execution nobody asked for.
- A call that reaches the deadline times out.
- The table's lock is a leaf and no lock is held while waiting; a resolution
  wakes its waiter after the table lock is released.

Request ids are ``c<boot>.<n>``: a value fixed when the Hub starts and a counter,
never reused, so a late reply cannot satisfy a different call.
"""

from __future__ import annotations

import logging
import secrets
import threading
from typing import ClassVar, Self, final

from punt_lux.hub.call_entry import CallEntry, SessionTicket
from punt_lux.hub.call_outcomes import (
    CallOutcome,
    Lost,
    ProviderBusyError,
    Refused,
    Replied,
    TimedOut,
)
from punt_lux.wire.model.messages.relay_frames import (
    RefusalFrame,
    ReplyFrame,
    RequestFrame,
)

__all__ = ["ClientCalls", "PendingCall"]

logger = logging.getLogger(__name__)


@final
class PendingCall:
    """One request entered in the table: its frame to send and its outcome to await."""

    __slots__ = ("_calls", "_entry", "_frame")

    _calls: ClientCalls
    _entry: CallEntry
    _frame: RequestFrame

    def __new__(cls, calls: ClientCalls, entry: CallEntry, frame: RequestFrame) -> Self:
        self = super().__new__(cls)
        self._calls = calls
        self._entry = entry
        self._frame = frame
        return self

    @property
    def frame(self) -> RequestFrame:
        """The request frame the session's writer sends."""
        return self._frame

    def wait(self) -> CallOutcome:
        """Block until the call's one outcome, at most the deadline.

        Waiting again reports the same outcome.
        """
        return self._calls.await_outcome(self._frame.request_id, self._entry)


@final
class ClientCalls:
    """The pending calls of every provider session, behind one leaf lock."""

    DEADLINE_S: ClassVar[float] = 15.0
    PER_SESSION_LIMIT: ClassVar[int] = 8
    MAX_REPLY_BYTES: ClassVar[int] = 256 * 1024
    # No client frame is read past this size: a connected client cannot make the
    # Hub parse and hold an unbounded frame before any cap applies.
    MAX_FRAME_BYTES: ClassVar[int] = 2 * MAX_REPLY_BYTES

    __slots__ = ("_boot", "_deadline_s", "_lock", "_pending", "_serial", "_sessions")

    _boot: str
    _deadline_s: float
    _lock: threading.Lock
    _pending: dict[str, CallEntry]
    _sessions: int
    _serial: int

    def __new__(cls, boot: str | None = None, deadline_s: float = DEADLINE_S) -> Self:
        self = super().__new__(cls)
        self._boot = boot if boot is not None else secrets.token_hex(4)
        self._deadline_s = deadline_s
        self._lock = threading.Lock()
        self._pending = {}
        self._sessions = 0
        self._serial = 0
        return self

    def open_session(self) -> SessionTicket:
        """Return the ticket for a new listen session."""
        with self._lock:
            self._sessions += 1
            return SessionTicket(self._sessions)

    def enter(
        self,
        ticket: SessionTicket,
        service: str,
        operation: str,
        payload: dict[str, object],
    ) -> PendingCall:
        """Enter a request for ``ticket``'s session and return it to send and await.

        Raises:
            ProviderBusyError: If the session already has its limit pending; the
                request is not entered and must not be sent.
        """
        with self._lock:
            if not ticket.ended and self._count(ticket) >= self.PER_SESSION_LIMIT:
                msg = "provider busy"
                raise ProviderBusyError(msg)
            self._serial += 1
            request_id = f"c{self._boot}.{self._serial}"
            entry = CallEntry(ticket, self._deadline_s)
            if ticket.ended:
                entry.conclude(Lost())
                entry.wake()
            else:
                self._pending[request_id] = entry
        frame = RequestFrame(
            request_id=request_id, service=service, operation=operation, payload=payload
        )
        return PendingCall(self, entry, frame)

    def reply(self, ticket: SessionTicket, frame: ReplyFrame, size: int = 0) -> bool:
        """Resolve the call ``frame`` answers; return whether one was resolved.

        ``size`` is the frame's length as received, so the cap is checked without
        serializing the payload again; a caller with no raw frame omits it.
        """
        if size > self.MAX_REPLY_BYTES:
            outcome: CallOutcome = Refused("fault", "reply too large")
        else:
            outcome = Replied(frame.payload)
        return self._resolve(ticket, frame.request_id, outcome)

    def refuse(self, ticket: SessionTicket, frame: RefusalFrame) -> bool:
        """Resolve the call ``frame`` refuses; return whether one was resolved."""
        return self._resolve(
            ticket, frame.request_id, Refused(frame.code, frame.reason)
        )

    def end_session(self, ticket: SessionTicket) -> int:
        """Resolve every call pending on the session as lost; return how many.

        The session is marked ended, so a request entered for it afterwards is
        lost at once rather than queued where no writer will send it.
        """
        with self._lock:
            ticket.end()
            ended = [
                (request_id, entry)
                for request_id, entry in self._pending.items()
                if entry.was_sent_to(ticket)
            ]
            for request_id, entry in ended:
                entry.conclude(Lost())
                del self._pending[request_id]
        for _, entry in ended:
            entry.wake()
        return len(ended)

    def await_outcome(self, request_id: str, entry: CallEntry) -> CallOutcome:
        """Wait for the entry's outcome; at the deadline, time it out if pending."""
        entry.wait_until_deadline()
        with self._lock:
            outcome = entry.outcome
            if outcome is None:
                outcome = TimedOut()
                entry.conclude(outcome)
                self._pending.pop(request_id, None)
        entry.wake()
        return outcome

    def _resolve(
        self, ticket: SessionTicket, request_id: str, outcome: CallOutcome
    ) -> bool:
        with self._lock:
            entry = self._pending.get(request_id)
            if entry is None:
                logger.info("dropped a frame for unknown request %s", request_id)
                return False
            if not entry.was_sent_to(ticket):
                logger.warning(
                    "dropped a frame for request %s from a session it was not sent to",
                    request_id,
                )
                return False
            entry.conclude(outcome)
            del self._pending[request_id]
        entry.wake()
        return True

    def _count(self, ticket: SessionTicket) -> int:
        return sum(1 for entry in self._pending.values() if entry.was_sent_to(ticket))
