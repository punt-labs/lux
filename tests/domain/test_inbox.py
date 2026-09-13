"""``inbox_depth_for`` -- the queued-but-undelivered count, per ``qsize()``.

Each test uses its own unique :class:`ConnectionId` since ``_inboxes`` is
process-global module state shared across the test session.
"""

from __future__ import annotations

from collections import deque
from typing import Self, final

from punt_lux.domain.hub import inbox as inbox_mod
from punt_lux.domain.hub.hub import hub
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.inbox import (
    drain_inbox,
    drop_session,
    ensure_writer,
    inbox_depth_for,
    inbox_for,
    next_event,
    offer,
)
from punt_lux.domain.hub.inbox_queue import BoundedInbox
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.messages.observer import ObserverMessage


@final
class _LockWatchingQueue(deque[ObserverMessage]):
    """A deque that records whether ``_inboxes_lock`` is held during ``append``.

    ``BoundedInbox`` stores its messages in a deque and delivers via ``append``,
    so the spy watches ``append`` -- the operation ``BoundedInbox.put`` calls once
    it is inside the inbox's own condition.

    D1 fidelity control: ``offer`` must hold ``_inboxes_lock`` across BOTH the
    ``get`` that finds the inbox AND the ``put`` that delivers into it, so a
    concurrent ``drop_session`` cannot pop the queue between the two and turn a
    false ``True`` delivery into an orphan (M1: ``¬(delivered ∧ lost)``, modelled
    in ``docs/menu_lifecycle.tex``). The old code released the lock after the get
    and put outside it -- observed here as ``locked() == False`` at append time.
    """

    _held_at_put: bool
    _put_seen: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._held_at_put = False
        self._put_seen = False
        return self

    def append(self, item: ObserverMessage) -> None:
        self._held_at_put = inbox_mod._inboxes_lock.locked()
        self._put_seen = True
        super().append(item)

    @property
    def held_at_put(self) -> bool:
        """Whether ``_inboxes_lock`` was held when ``append`` last ran."""
        return self._held_at_put

    @property
    def put_seen(self) -> bool:
        """Whether ``append`` ran at all -- guards against a vacuous pass."""
        return self._put_seen


def test_offer_puts_under_the_inboxes_lock() -> None:
    """D1: ``offer`` delivers with ``_inboxes_lock`` held, closing the get/put race.

    Places a spy queue in ``_inboxes`` and asserts the lock is held at the moment
    ``offer`` puts into it. Fails on the pre-fix code, which released the lock
    between the lookup and the put.
    """
    connection = ConnectionId("c-offer-d1")
    spy = _LockWatchingQueue()
    inbox = BoundedInbox(connection)
    inbox._queue = spy  # watch the inbox's underlying deque at delivery time
    with inbox_mod._inboxes_lock:
        inbox_mod._inboxes[connection] = inbox

    assert offer(connection, ObserverMessage(topic="t", payload={})) is True

    assert spy.put_seen
    assert spy.held_at_put

    drop_session(connection)  # cleanup: process-global _inboxes


def test_writer_puts_under_the_inboxes_lock() -> None:
    """WG: the Hub-writer's put runs with ``_inboxes_lock`` held, same as ``offer``.

    Places a spy queue in ``_inboxes`` before ``ensure_writer`` binds a fresh
    writer, then publishes through the Hub and asserts the lock was held at the
    moment the writer's ``put`` delivered. Fails on the pre-fix code, which
    released the lock between ``inbox_for``'s lookup and the put.
    """
    connection = ConnectionId("c-writer-wg")
    topic = Topic("wg.topic")
    spy = _LockWatchingQueue()
    inbox = BoundedInbox(connection)
    inbox._queue = spy  # watch the inbox's underlying deque at delivery time
    with inbox_mod._inboxes_lock:
        inbox_mod._inboxes[connection] = inbox

    ensure_writer(connection)
    hub.subscribe(connection, topic)
    delivered = hub.publish(connection, topic, {"k": "v"})

    assert delivered == 1
    assert spy.put_seen
    assert spy.held_at_put

    hub_display.drop_connection(connection)  # cleanup: production singletons


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


def test_ensure_writer_arms_an_inbox_even_when_a_listener_writer_exists() -> None:
    """F1: a listener session's menu_set click lands, not offer-dropped.

    A ``HubListenSession`` registers its own Hub writer directly
    (``deliver_event``), so ``hub.has_writer`` is already True when that session
    later calls ``menu_set``. ``ensure_writer`` must still create the inbox queue,
    or ``offer`` (the menu-event delivery path) finds none and drops a LIVE
    session's click. Fail-on-current: the pre-fix short-circuit returned before
    creating the inbox, so ``offer`` returned ``False``.
    """
    connection = ConnectionId("c-listener-menu")
    # The listener leg: a Hub writer bound with no inbox, exactly as ws_listen does.
    hub.register_writer(connection, lambda _msg: True)
    assert hub.has_writer(connection)
    assert inbox_depth_for(connection) == 0  # no inbox yet

    ensure_writer(connection)  # menu_set's admit calls this on an identified owner

    # The menu-event path delivers, because the inbox now exists despite the
    # pre-existing listener writer.
    assert offer(connection, ObserverMessage(topic="lux.menu", payload={})) is True
    assert inbox_depth_for(connection) == 1

    hub_display.drop_connection(connection)  # cleanup: production singletons
    assert inbox_depth_for(connection) == 0


def test_ensure_writer_is_idempotent_and_rebinds_nothing_on_a_second_call() -> None:
    """A second ``ensure_writer`` call on an already-writered connection no-ops."""
    connection = ConnectionId("c-depth-ensure-writer-idempotent")

    ensure_writer(connection)
    ensure_writer(connection)  # must not raise, must not rebind

    assert hub.has_writer(connection)
    hub_display.drop_connection(connection)  # cleanup: production singletons


def test_stale_writer_after_reconnect_does_not_deliver_into_the_new_session() -> None:
    """WG2: a publish snapshotted under a departed session drops after reconnect.

    ``stale_writer`` stands in for the closure ``Hub.publish``'s
    snapshot-then-invoke fan-out captured before the departure -- exactly
    what a slow invocation holds onto across the window between the
    snapshot and the actual call. Firing it after a same-identity reconnect
    must not land in the reconnected session's live inbox; the currency
    check recognizes the staleness and drops the message instead of
    delivering it to the wrong recipient
    (``docs/writer_publish_generation.tex``, WG2).
    """
    connection = ConnectionId("c-writer-stale-gen")
    topic = Topic("wg2.stale")

    ensure_writer(connection)  # G1
    # The writer Hub.publish's snapshot would have captured for G1.
    stale_writer = hub._writers.writer_for(connection)

    hub_display.drop_connection(connection)  # G1 departs
    ensure_writer(connection)  # G2 reconnects on the same ConnectionId

    spy = _LockWatchingQueue()
    inbox_for(connection)._queue = spy  # watch G2's live inbox for a delivery

    stale_writer(ObserverMessage(topic=topic, payload={"k": "v"}))

    assert not spy.put_seen  # dropped, never delivered into the successor's inbox

    hub_display.drop_connection(connection)  # cleanup: production singletons


def test_stale_writer_publish_reports_zero_delivered_not_one() -> None:
    """WG2 + the delivered-count contract: a stale no-op must not be counted.

    ``Hub.publish``'s docstring promises the count of subscribers that
    *actually received* the message. Before this fix, the loop counted every
    handler invocation that did not raise -- so a stale writer's WG2 no-op
    (module docstring above) was silently counted as a delivery, reporting
    ``delivered=1`` for a message that reached nobody. Rebinding the
    connection's writer without departing leaves the STALE writer's own
    subscription in place -- exactly the shape ``Hub.publish``'s
    snapshot-then-invoke fan-out produces when a reconnect lands between the
    snapshot and the call -- so the currency check inside ``_writer`` fires
    for real, and the count must reflect that nothing was delivered.
    """
    connection = ConnectionId("c-writer-stale-not-delivered")
    topic = Topic("wg2.notdelivered")

    ensure_writer(connection)  # G1 binds a writer + inbox
    hub.subscribe(connection, topic)  # subscription references G1's writer
    stale_writer = hub._writers.writer_for(connection)

    def _new_writer(_message: ObserverMessage) -> bool:
        return True

    # G2 takes over the connection's writer slot without a departure, so the
    # existing subscription -- still bound to G1's `stale_writer` closure --
    # survives the rebind untouched.
    hub.register_writer(connection, _new_writer)
    assert hub._subscriptions.snapshot_subscribers(connection, topic) == (stale_writer,)

    delivered = hub.publish(connection, topic, {"k": "v"})

    assert delivered == 0

    hub_display.drop_connection(connection)  # cleanup: production singletons


def test_live_writer_publish_reports_one_delivered() -> None:
    """The normal case the stale-count fix must not disturb: a live delivery."""
    connection = ConnectionId("c-writer-live-delivered")
    topic = Topic("wg2.delivered")

    ensure_writer(connection)
    hub.subscribe(connection, topic)

    delivered = hub.publish(connection, topic, {"k": "v"})

    assert delivered == 1

    hub_display.drop_connection(connection)  # cleanup: production singletons


def test_current_writer_delivers_after_a_drain_inbox_swap() -> None:
    """The currency check never fires against a live writer or ``drain_inbox``.

    ``drain_inbox`` replaces the connection's ``BoundedInbox`` with a fresh
    one for a session that has NOT departed -- it never touches the writer
    registry, so the still-current writer's next publish must still deliver
    normally after the swap.
    """
    connection = ConnectionId("c-writer-current-gen")
    topic = Topic("wg2.current")

    ensure_writer(connection)
    hub.subscribe(connection, topic)

    drain_inbox(connection)  # swaps the inbox; leaves the writer registration alone

    delivered = hub.publish(connection, topic, {"k": "v"})
    assert delivered == 1

    event = next_event(connection, timeout=1.0)
    assert event is not None
    assert event.payload == {"k": "v"}

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
