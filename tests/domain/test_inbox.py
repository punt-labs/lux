"""``inbox_depth_for`` -- the queued-but-undelivered count, per ``qsize()``.

Each test uses its own unique :class:`ConnectionId` since ``_inboxes`` is
process-global module state shared across the test session.
"""

from __future__ import annotations

from punt_lux.domain.hub.inbox import drop_session, inbox_depth_for, inbox_for
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage


def test_an_unknown_connection_reports_zero() -> None:
    assert inbox_depth_for(ConnectionId("never-seen")) == 0


def test_reports_the_number_of_queued_messages() -> None:
    connection = ConnectionId("c-depth-1")
    inbox = inbox_for(connection)
    inbox.put(ObserverMessage(topic="t", payload={}))
    inbox.put(ObserverMessage(topic="t", payload={}))

    assert inbox_depth_for(connection) == 2


def test_a_freshly_created_inbox_reports_zero() -> None:
    connection = ConnectionId("c-depth-2")
    inbox_for(connection)

    assert inbox_depth_for(connection) == 0


def test_drop_session_resets_the_depth_to_zero() -> None:
    connection = ConnectionId("c-depth-3")
    inbox_for(connection).put(ObserverMessage(topic="t", payload={}))
    assert inbox_depth_for(connection) == 1

    drop_session(connection)

    assert inbox_depth_for(connection) == 0
