"""``inbox_depth_for`` -- the queued-but-undelivered count, per ``qsize()``.

Each test uses its own unique :class:`ConnectionId` since ``_inboxes`` is
process-global module state shared across the test session.
"""

from __future__ import annotations

from punt_lux.domain.hub.hub import hub
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.inbox import (
    drop_session,
    ensure_writer,
    inbox_depth_for,
    inbox_for,
)
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


def test_ensure_writer_binds_drop_session_as_the_departure_sink() -> None:
    """A fresh writer is registered alongside a departure sink, at connect time.

    Departing the connection through the production ``hub_display`` singleton
    must drain its inbox without any transport-layer code passing
    ``drop_session`` explicitly -- the binding done here is what closes that
    gap.
    """
    connection = ConnectionId("c-depth-ensure-writer")
    inbox_for(connection).put(ObserverMessage(topic="t", payload={}))

    ensure_writer(connection)
    assert hub.has_writer(connection)

    hub_display.drop_connection(connection)

    assert not hub.has_writer(connection)
    assert inbox_depth_for(connection) == 0


def test_ensure_writer_is_idempotent_and_rebinds_nothing_on_a_second_call() -> None:
    """A second ``ensure_writer`` call on an already-writered connection no-ops."""
    connection = ConnectionId("c-depth-ensure-writer-idempotent")

    ensure_writer(connection)
    ensure_writer(connection)  # must not raise, must not rebind

    assert hub.has_writer(connection)
    hub_display.drop_connection(connection)  # cleanup: production singletons
