"""``inbox_depth_for`` -- the queued-but-undelivered count, per ``qsize()``.

Each test uses its own unique :class:`ConnectionId` since ``_inboxes`` is
process-global module state shared across the test session.
"""

from __future__ import annotations

import queue
from typing import Self, final

from punt_lux.domain.hub import inbox as inbox_mod
from punt_lux.domain.hub.hub import hub
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.inbox import (
    drop_session,
    ensure_writer,
    inbox_depth_for,
    inbox_for,
    next_event,
    offer,
)
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.messages.observer import ObserverMessage


@final
class _LockWatchingQueue(queue.SimpleQueue[ObserverMessage]):
    """A SimpleQueue that records whether ``_inboxes_lock`` is held during ``put``.

    D1 fidelity control: ``offer`` must hold ``_inboxes_lock`` across BOTH the
    ``get`` that finds the inbox AND the ``put`` that delivers into it, so a
    concurrent ``drop_session`` cannot pop the queue between the two and turn a
    false ``True`` delivery into an orphan (M1: ``¬(delivered ∧ lost)``, modelled
    in ``docs/menu_lifecycle.tex``). The old code released the lock after the get
    and put outside it -- observed here as ``locked() == False`` at put time.
    """

    _held_at_put: bool
    _put_seen: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._held_at_put = False
        self._put_seen = False
        return self

    def put(
        self, item: ObserverMessage, block: bool = True, timeout: float | None = None
    ) -> None:
        self._held_at_put = inbox_mod._inboxes_lock.locked()
        self._put_seen = True
        super().put(item, block, timeout)

    @property
    def held_at_put(self) -> bool:
        """Whether ``_inboxes_lock`` was held when ``put`` last ran."""
        return self._held_at_put

    @property
    def put_seen(self) -> bool:
        """Whether ``put`` was called at all -- guards against a vacuous pass."""
        return self._put_seen


def test_offer_puts_under_the_inboxes_lock() -> None:
    """D1: ``offer`` delivers with ``_inboxes_lock`` held, closing the get/put race.

    Places a spy queue in ``_inboxes`` and asserts the lock is held at the moment
    ``offer`` puts into it. Fails on the pre-fix code, which released the lock
    between the lookup and the put.
    """
    connection = ConnectionId("c-offer-d1")
    spy = _LockWatchingQueue()
    with inbox_mod._inboxes_lock:
        inbox_mod._inboxes[connection] = spy

    assert offer(connection, ObserverMessage(topic="t", payload={})) is True

    assert spy.put_seen
    assert spy.held_at_put

    drop_session(connection)  # cleanup: process-global _inboxes


def test_offer_on_a_dropped_session_does_not_resurrect_an_inbox() -> None:
    """D1: a message for a session whose inbox is gone is refused, never delivered.

    The ``provider_gone`` half of M1 -- ``offer`` returns ``False`` and creates no
    queue, so nothing lands in an orphan.
    """
    connection = ConnectionId("c-offer-gone")
    inbox_for(connection)
    drop_session(connection)

    assert offer(connection, ObserverMessage(topic="t", payload={})) is False
    assert inbox_depth_for(connection) == 0


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


def test_ensure_writer_installs_a_fresh_writer_after_a_same_identity_reap() -> None:
    """RR2: the real ``ensure_writer`` entry point installs a fresh writer.

    Exercises ``ensure_writer``'s own ``if hub.has_writer(connection_id):
    return`` early-return branch for real -- not ``hub.register_writer``
    called directly -- because that branch is the original bug's mechanism
    (design doc Section 1.1): before the fix, a departed connection's writer
    binding survived the reap, so a reconnecting session's ``ensure_writer``
    call returned early and silently inherited the dead predecessor's
    binding instead of installing its own.
    """
    connection = ConnectionId("c-depth-rr2")
    topic = Topic("rr2.topic")

    ensure_writer(connection)
    hub.subscribe(connection, topic)
    assert hub.has_writer(connection)
    assert hub.topics_for(connection) == frozenset({topic})

    # Depart -- the full cascade drops the writer and subscriptions together.
    hub_display.drop_connection(connection)
    assert not hub.has_writer(connection)
    assert hub.topics_for(connection) == frozenset()

    # The real reconnect entry point, exercised for real: the
    # `if hub.has_writer(connection_id): return` branch is now on the
    # covered path, since has_writer is correctly False post-departure.
    ensure_writer(connection)

    assert hub.has_writer(connection)
    assert hub.topics_for(connection) == frozenset()  # nothing inherited

    # Prove the fresh writer genuinely works, not merely "is bound":
    # publish only reaches a live subscription, so re-subscribe and confirm
    # the message actually lands in the reconnected session's own inbox.
    hub.subscribe(connection, topic)
    delivered = hub.publish(connection, topic, {"k": "v"})
    assert delivered == 1
    event = next_event(connection, timeout=1.0)
    assert event is not None
    assert event.payload == {"k": "v"}

    hub_display.drop_connection(connection)  # cleanup: production singletons
