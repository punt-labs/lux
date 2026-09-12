"""Per-connection inbox queues for MCP-side Agent Subscribe delivery.

The Hub writer for an MCP session puts each ``Hub.publish`` fan-out onto a
``queue.SimpleQueue`` keyed by the session's ``ConnectionId``; ``recv``
consumes one message per call.
"""

from __future__ import annotations

import queue
import threading

from punt_lux.domain.hub.hub import hub
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage

__all__ = [
    "drain_inbox",
    "drop_session",
    "ensure_writer",
    "inbox_depth_for",
    "inbox_for",
    "next_event",
    "offer",
]


# SimpleQueue's get/put are thread-safe; the lock guards allocation of
# a new queue on first subscribe so two callers never see different
# instances for the same connection.
_inboxes: dict[ConnectionId, queue.SimpleQueue[ObserverMessage]] = {}
_inboxes_lock = threading.Lock()


def inbox_for(connection_id: ConnectionId) -> queue.SimpleQueue[ObserverMessage]:
    """Return (creating if needed) the connection's inbox queue."""
    with _inboxes_lock:
        if (existing := _inboxes.get(connection_id)) is not None:
            return existing
        _inboxes[connection_id] = queue.SimpleQueue()
        return _inboxes[connection_id]


def drain_inbox(connection_id: ConnectionId) -> tuple[ObserverMessage, ...]:
    """Snapshot then clear the connection's inbox; used by tests.

    Swaps the live queue with a fresh empty one under the lock so a
    concurrent producer's ``put`` lands in the new queue, never racing
    with the drain loop on the snapshot.
    """
    with _inboxes_lock:
        old = _inboxes.get(connection_id)
        if old is None:
            return ()
        _inboxes[connection_id] = queue.SimpleQueue()
    drained: list[ObserverMessage] = []
    while True:
        try:
            drained.append(old.get_nowait())
        except queue.Empty:
            break
    return tuple(drained)


def next_event(connection_id: ConnectionId, timeout: float) -> ObserverMessage | None:
    """Block for the next inbox message; return ``None`` on timeout."""
    inbox = inbox_for(connection_id)
    try:
        return inbox.get(timeout=timeout)
    except queue.Empty:
        return None


def ensure_writer(connection_id: ConnectionId) -> None:
    """Ensure the connection's inbox queue and cleanup, and a Hub writer.

    The inbox queue and its ``drop_session`` cleanup are armed for EVERY caller,
    even one that already has a Hub writer: a ``menu_set`` owner needs an inbox
    for its menu clicks to land on -- ``offer`` never resurrects a missing one --
    and a listener session installs its own Hub writer (``deliver_event``)
    without ever creating an inbox. The Hub writer is registered only when none
    exists, so a listener's writer is never clobbered by the inbox writer. The
    whole sequence runs under the Hub store's write lock, so it can never
    straddle a departure cascade the way a same-identity reconnect could
    otherwise land inside.
    """
    with hub_display.write_lock():
        hub_display.register_client(connection_id)
        # The inbox and its cleanup exist independently of any Hub writer, so a
        # listener session (writer already bound) still receives menu_set clicks.
        # Resolves the live queue per call, so a ``drain_inbox`` swap doesn't strand it.
        inbox_for(connection_id)
        hub_display.bind_departure_sink(connection_id, drop_session)
        if hub.has_writer(connection_id):
            return

        def _writer(message: ObserverMessage) -> None:
            inbox_for(connection_id).put(message)

        hub.register_writer(connection_id, _writer)


def inbox_depth_for(connection_id: ConnectionId) -> int:
    """Return the queued-but-undelivered count -- observational, per ``qsize()``."""
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
    return inbox.qsize() if inbox is not None else 0


def drop_session(connection_id: ConnectionId) -> None:
    """Release the session's inbox queue on disconnect. Idempotent."""
    with _inboxes_lock:
        _inboxes.pop(connection_id, None)


def offer(connection_id: ConnectionId, message: ObserverMessage) -> bool:
    """Deliver ``message`` to an existing inbox, never resurrecting a dropped one.

    Returns whether an inbox was present to receive it. Unlike the session
    writer's ``inbox_for(...).put`` — which creates a queue on demand — this reads
    with ``.get``, so a message for a session whose ``drop_session`` already ran
    finds no inbox and is not delivered. The get AND the put run under one hold of
    ``_inboxes_lock``, so a concurrent ``drop_session`` cannot interleave between
    them: either the inbox is present and the message is put atomically (``True``),
    or it is already gone (``False`` → ``provider_gone``). Reading the queue and
    then putting outside the lock would let a departure pop it in between and
    deliver into an orphan while still reporting ``True`` — the false-delivery the
    menu-event M1 gate forbids (``¬(delivered ∧ lost)``, modelled in
    ``docs/menu_lifecycle.tex``).
    """
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
        if inbox is None:
            return False
        inbox.put(message)
        return True
