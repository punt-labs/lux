"""Per-connection inbox registry for MCP-side Agent Subscribe delivery.

The Hub writer for an MCP session puts each ``Hub.publish`` fan-out onto a
:class:`~punt_lux.domain.hub.inbox_queue.BoundedInbox` keyed by the session's
``ConnectionId``; ``recv`` consumes one message per call. This module owns the
registry -- which connection has an inbox, and the Hub-writer and departure-sink
wiring around it -- while the inbox itself owns what a single connection's queue
does, including the bounded drop-oldest backstop.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from punt_lux.domain.hub.hub import hub
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.inbox_queue import BoundedInbox

if TYPE_CHECKING:
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

logger = logging.getLogger(__name__)

# The lock guards allocation of a new inbox on first subscribe so two callers
# never see different instances for the same connection.
_inboxes: dict[ConnectionId, BoundedInbox] = {}
_inboxes_lock = threading.Lock()


def _inbox_for_locked(connection_id: ConnectionId) -> BoundedInbox:
    """Return (creating if needed) the connection's inbox; caller holds the lock."""
    if (existing := _inboxes.get(connection_id)) is not None:
        return existing
    _inboxes[connection_id] = BoundedInbox(connection_id)
    return _inboxes[connection_id]


def inbox_for(connection_id: ConnectionId) -> BoundedInbox:
    """Return (creating if needed) the connection's inbox."""
    with _inboxes_lock:
        return _inbox_for_locked(connection_id)


def drain_inbox(connection_id: ConnectionId) -> tuple[ObserverMessage, ...]:
    """Snapshot then clear the connection's inbox; used by tests.

    Swaps the live inbox for a fresh one under the lock so a concurrent
    producer's ``put`` lands in the new inbox, never racing with the drain on
    the snapshot.
    """
    with _inboxes_lock:
        old = _inboxes.get(connection_id)
        if old is None:
            return ()
        _inboxes[connection_id] = BoundedInbox(connection_id)
    return old.drain()


def next_event(connection_id: ConnectionId, timeout: float) -> ObserverMessage | None:
    """Block for the next inbox message; return ``None`` on timeout."""
    return inbox_for(connection_id).get(timeout)


def ensure_writer(connection_id: ConnectionId) -> None:
    """Ensure the connection's inbox and cleanup, and a Hub writer.

    The inbox and its ``drop_session`` cleanup are armed for EVERY caller, even
    one that already has a Hub writer: a ``menu_set`` owner needs an inbox for
    its menu clicks to land on -- ``offer`` never resurrects a missing one --
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
        inbox_for(connection_id)
        hub_display.bind_departure_sink(connection_id, drop_session)
        if hub.has_writer(connection_id):
            return

        def _writer(message: ObserverMessage) -> bool:
            """Deliver atomically, checked for writer-generation currency.

            Shares ``offer``'s WG guarantee -- the resolve and the put are one
            atomic step under ``_inboxes_lock`` -- and closes WG2:
            ``Hub.publish``'s snapshot-then-invoke fan-out can capture this
            closure long before it fires, long enough for a same-identity
            reconnect to already own a fresh writer by the time this one
            finally runs. The currency check, under the SAME lock hold as the
            put, asks whether ``_writer`` is still the registration ``hub``
            currently binds for this connection; if not, the put is skipped
            entirely rather than landing in the reconnected session's live
            inbox, and ``False`` reports the non-delivery to ``Hub.publish``'s
            count. See ``docs/writer_publish_generation.tex`` (WG2).
            """
            with _inboxes_lock:
                if not hub.writer_is_current(connection_id, _writer):
                    logger.debug(
                        "%s writer stale (superseded by reconnect); "
                        "dropping publish on %r",
                        connection_id,
                        message.topic,
                    )
                    return False
                _inbox_for_locked(connection_id).put(message)
                return True

        hub.register_writer(connection_id, _writer)


def inbox_depth_for(connection_id: ConnectionId) -> int:
    """Return the queued-but-undelivered count -- observational, per ``qsize()``."""
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
    return inbox.depth() if inbox is not None else 0


def drop_session(connection_id: ConnectionId) -> None:
    """Release the session's inbox on disconnect. Idempotent."""
    with _inboxes_lock:
        _inboxes.pop(connection_id, None)


def offer(connection_id: ConnectionId, message: ObserverMessage) -> bool:
    """Deliver ``message`` to an existing inbox, never resurrecting a dropped one.

    Returns whether an inbox was present to receive it. Unlike the session
    writer's ``inbox_for(...).put`` -- which creates an inbox on demand -- this
    reads with ``.get``, so a message for a session whose ``drop_session`` already
    ran finds no inbox and is not delivered. The get AND the put run under one
    hold of ``_inboxes_lock``, so a concurrent ``drop_session`` cannot interleave
    between them: either the inbox is present and the message is put atomically
    (``True``), or it is already gone (``False`` -> ``provider_gone``). Reading the
    inbox and then putting outside the lock would let a departure pop it in between
    and deliver into an orphan while still reporting ``True`` -- the false-delivery
    the menu-event M1 gate forbids (``not (delivered and lost)``, modelled in
    ``docs/menu_lifecycle.tex``). ``_writer`` shares this atomicity (WG,
    ``docs/writer_publish_generation.tex``).
    """
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
        if inbox is None:
            return False
        inbox.put(message)
        return True
