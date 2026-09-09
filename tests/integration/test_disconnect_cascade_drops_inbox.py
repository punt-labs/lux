"""``disconnect_connection`` releases the MCP inbox via the registered sink.

The lifecycle cascade owns no transport state of its own. A transport binds
its own per-connection cleanup once, at connect time
(:class:`~punt_lux.domain.hub.departure_sinks.DepartureSinks`), so resources
held outside the domain — the per-session MCP inbox queue, file handles,
etc. — are released in the same cascade rather than leaking until process
exit.
"""

from __future__ import annotations

import contextlib
import queue

from punt_lux.domain.hub import inbox
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.lifecycle import disconnect_connection
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage


def test_drop_session_releases_inbox_queue() -> None:
    """``drop_session`` purges the per-connection inbox entry."""
    connection_id = ConnectionId("drop-session-1")
    q = inbox.inbox_for(connection_id)
    q.put(ObserverMessage(topic="t", payload={}))

    inbox.drop_session(connection_id)

    fresh = inbox.inbox_for(connection_id)
    assert fresh is not q
    with_timeout: ObserverMessage | None = None
    with contextlib.suppress(queue.Empty):
        with_timeout = fresh.get_nowait()
    assert with_timeout is None


def test_disconnect_cascade_fires_a_registered_sink() -> None:
    """The cascade's transport-sink leg fires whatever sink was bound."""
    connection_id = ConnectionId("cascade-sink-1")
    store = HubDisplay(hub=Hub())
    store.register_client(connection_id)
    invocations: list[ConnectionId] = []

    def _sink(conn: ConnectionId) -> None:
        invocations.append(conn)

    store.bind_departure_sink(connection_id, _sink)

    disconnect_connection(connection_id, hub_display=store)

    assert invocations == [connection_id]


def test_disconnect_cascade_drops_real_inbox() -> None:
    """Bound to ``inbox.drop_session``, the cascade releases the real inbox."""
    connection_id = ConnectionId("cascade-inbox-1")
    original = inbox.inbox_for(connection_id)
    original.put(ObserverMessage(topic="t", payload={}))
    store = HubDisplay(hub=Hub())
    store.bind_departure_sink(connection_id, inbox.drop_session)

    disconnect_connection(connection_id, hub_display=store)

    fresh = inbox.inbox_for(connection_id)
    assert fresh is not original
