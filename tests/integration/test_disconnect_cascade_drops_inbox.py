"""``disconnect_connection`` releases the MCP inbox via injected callback.

The lifecycle cascade owns no transport state. Callers commit to an
explicit ``on_disconnect`` sink so resources held outside the domain —
the per-session MCP inbox queue, file handles, etc. — are released in
the same cascade rather than leaking until process exit.
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


def test_disconnect_cascade_invokes_on_disconnect_sink() -> None:
    """The lifecycle cascade fires the required ``on_disconnect`` callback."""
    connection_id = ConnectionId("cascade-sink-1")
    isolated_hub_display = HubDisplay()
    isolated_hub = Hub()
    invocations: list[ConnectionId] = []

    disconnect_connection(
        connection_id,
        invocations.append,
        hub_display=isolated_hub_display,
        hub=isolated_hub,
    )

    assert invocations == [connection_id]


def test_disconnect_cascade_drops_real_inbox() -> None:
    """Wired with ``inbox.drop_session`` the cascade releases the inbox."""
    connection_id = ConnectionId("cascade-inbox-1")
    original = inbox.inbox_for(connection_id)
    original.put(ObserverMessage(topic="t", payload={}))

    disconnect_connection(
        connection_id,
        inbox.drop_session,
        hub_display=HubDisplay(),
        hub=Hub(),
    )

    fresh = inbox.inbox_for(connection_id)
    assert fresh is not original
