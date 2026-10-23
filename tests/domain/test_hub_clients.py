"""HubClientRegistry — session roster reads and writes are serialized.

Bind, identify, and unbind run on the transport's connection threads while
``list_clients`` reads on a tool thread, so every access to the roster is
guarded by the registry's lock. These tests exercise the ``record`` upsert (bare
registration and identity declaration are the same primitive), the lease renewal
and the lease-filtered live reads (driven by an injected clock), the repository
projection, and hammer the registry from many threads to prove the reads stay
coherent and no thread raises.
"""

from __future__ import annotations

import threading
import time
from typing import final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.presence_writes import PresenceWrites
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.hub.session_write import SessionWrite
from punt_lux.domain.ids import ConnectionId


@final
class _Clock:
    """A hand-advanced monotonic clock, so lease expiry is deterministic."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _churn(
    reg: HubClientRegistry, conns: list[ConnectionId], stop: threading.Event
) -> None:
    """Record then discard every connection until told to stop."""
    while not stop.is_set():
        for conn in conns:
            _writes(reg).record(conn, None, UNOBSERVED)
        for conn in conns:
            _writes(reg).discard(conn)


def _read(reg: HubClientRegistry, stop: threading.Event) -> None:
    """Snapshot the roster until told to stop; every value is a session record."""
    while not stop.is_set():
        for value in reg.sessions().values():
            assert isinstance(value, ClientSession)


def test_record_is_idempotent_and_stamps_once() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    _writes(reg).record(conn, None, UNOBSERVED)
    first = reg.sessions()[conn].connected_at
    _writes(reg).record(conn, None, UNOBSERVED)
    # A re-record keeps the original connect time — age never resets.
    assert reg.sessions()[conn].connected_at == first


def test_a_bare_record_leaves_the_session_unidentified() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    _writes(reg).record(conn, None, UNOBSERVED)
    assert reg.sessions()[conn].identity is None


def test_record_with_identity_keeps_the_connect_time() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    _writes(reg).record(conn, None, UNOBSERVED)
    stamped = reg.sessions()[conn].connected_at

    identity = ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")
    _writes(reg).record(conn, identity, UNOBSERVED)

    session = reg.sessions()[conn]
    assert session.identity == identity
    # Declaring an identity records who, not when — the age is unchanged.
    assert session.connected_at == stamped


def test_a_later_bare_record_never_drops_a_declared_identity() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    _writes(reg).record(conn, identity, UNOBSERVED)
    # The connect path re-records without an identity; the declaration survives.
    _writes(reg).record(conn, None, UNOBSERVED)
    assert reg.sessions()[conn].identity == identity


def test_record_with_identity_registers_an_unseen_connection() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    assert reg.session_of(conn) is None
    _writes(reg).record(conn, ClientIdentity(kind="cli", name="lux-cli"), UNOBSERVED)
    assert reg.session_of(conn) is not None  # membership via the O(1) session read
    assert reg.sessions()[conn].identity is not None


def test_session_of_returns_the_record_or_none() -> None:
    reg = HubClientRegistry()
    identified = ConnectionId("identified")
    bare = ConnectionId("bare")
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    _writes(reg).record(identified, identity, UNOBSERVED)
    _writes(reg).record(bare, None, UNOBSERVED)
    identified_session = reg.session_of(identified)
    assert identified_session is not None
    assert identified_session.identity == identity
    bare_session = reg.session_of(bare)
    assert bare_session is not None  # registered but unidentified
    assert bare_session.identity is None
    assert reg.session_of(ConnectionId("never")) is None  # unknown connection


def test_discard_drops_the_identity_with_the_connection() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    _writes(reg).record(
        conn,
        ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux"),
        UNOBSERVED,
    )
    _writes(reg).discard(conn)
    assert reg.sessions() == {}


def _cli(name: str = "lux") -> ClientIdentity:
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def test_live_sessions_filters_an_expired_session_without_sweeping_it() -> None:
    """RD1: a read filters the live view; it never removes the registry entry."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _writes(reg).record(conn, _cli(), UNOBSERVED)
    assert conn in reg.live_sessions()

    clock.advance(91.0)  # past the 90s cli lease
    assert reg.live_sessions() == {}  # filtered out of the live view
    assert conn in reg.sessions()  # still registered — the read removed no one


def test_any_contact_renews_the_lease() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _writes(reg).record(conn, _cli(), UNOBSERVED)

    clock.advance(80.0)
    _writes(reg).record(
        conn, None, UNOBSERVED
    )  # a bare contact renews, keeping the declared identity
    clock.advance(80.0)  # 160s from the start, but only 80s since the renewal

    live = reg.live_sessions()
    assert conn in live  # still inside the 90s window from the renewal
    assert live[conn].identity == _cli()


def test_an_mcp_session_outlives_a_cli_session() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    cli, mcp = ConnectionId("cli"), ConnectionId("mcp")
    _writes(reg).record(cli, _cli(), UNOBSERVED)
    _writes(reg).record(
        mcp,
        ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux"),
        UNOBSERVED,
    )

    clock.advance(120.0)  # past the cli lease (90s), well within the mcp lease (1800s)
    live = reg.live_sessions()
    assert cli not in live
    assert mcp in live


def test_no_read_ever_removes_a_lapsed_session() -> None:
    """RD1: neither the raw read nor the live read sweeps a lapsed entry."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _writes(reg).record(conn, _cli(), UNOBSERVED)
    clock.advance(91.0)
    assert conn in reg.sessions()
    reg.live_sessions()  # a read; still non-destructive
    assert conn in reg.sessions()
    reg.named_sessions()  # a read; still non-destructive
    assert conn in reg.sessions()


def test_reap_lapsed_returns_who_lapsed_and_removes_only_them() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    lapsing, staying = ConnectionId("cli"), ConnectionId("mcp")
    _writes(reg).record(lapsing, _cli(), UNOBSERVED)
    _writes(reg).record(staying, _mcp(), UNOBSERVED)

    clock.advance(91.0)  # past the cli lease; the mcp lease (1800s) survives

    assert _writes(reg).reap_lapsed().lapsed == frozenset({lapsing})
    assert lapsing not in reg.sessions()  # actually removed, not just filtered
    assert staying in reg.sessions()


def test_reap_lapsed_is_empty_and_a_no_op_when_nothing_has_lapsed() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    _writes(reg).record(conn, _cli(), UNOBSERVED)
    assert _writes(reg).reap_lapsed().lapsed == frozenset()
    assert conn in reg.sessions()


def test_reap_lapsed_honors_its_exclusion() -> None:
    """The exclusion ``apply``'s renewed caller needs, at the registry layer."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _writes(reg).record(conn, _cli(), UNOBSERVED)
    clock.advance(91.0)  # past the 90s cli lease

    assert _writes(reg).reap_lapsed(exclude=frozenset({conn})).lapsed == frozenset()
    assert conn in reg.sessions()  # excluded, so left alone
    assert _writes(reg).reap_lapsed().lapsed == frozenset({conn})
    assert conn not in reg.sessions()


def test_reap_lapsed_cannot_wipe_a_renewal_that_races_it() -> None:
    """The TOCTOU a split compute-then-discard leaves open, closed by one lock.

    A round-1-era renewal path (``record``/``renew_if_registered``/
    ``attach_listener``) takes only the registry's own lock, not the Hub's
    ``StoreLock`` a departure sweep holds. A sweep that computes the lapsed
    set in one lock hold and discards each id in a second, separate hold
    leaves a gap: a renewal landing in that gap makes the connection live
    again, and the second hold discards it anyway -- a live client silently
    wiped under ordinary threaded load. ``reap_lapsed`` closes the
    gap by construction: nothing else can touch the registry while it
    holds the lock, so a concurrent renewal is strictly serialized before
    or after the sweep, never straddling it.
    """
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _writes(reg).record(conn, _cli(), UNOBSERVED)
    clock.advance(91.0)  # past the 90s cli lease

    renewal_attempted = threading.Event()
    renewal_done = threading.Event()

    def _renew_concurrently() -> None:
        renewal_attempted.set()
        _writes(reg).record(
            conn, None, UNOBSERVED
        )  # blocks on the registry's own lock until reap yields
        renewal_done.set()

    real_now = reg._clock

    def _now_that_races_a_renewal() -> float:
        # Fires from inside reap_lapsed's one critical section: start
        # the renewal thread and prove it is genuinely locked out (blocked on
        # the same lock, not just "hasn't run yet") before the sweep proceeds.
        if not renewal_attempted.is_set():
            threading.Thread(target=_renew_concurrently, daemon=True).start()
            assert renewal_attempted.wait(timeout=2.0)
            time.sleep(0.05)  # give the renewal thread time to reach lock.acquire()
            assert not renewal_done.is_set()
        return real_now()

    _writes(reg)._clock = _now_that_races_a_renewal

    reaped = _writes(reg).reap_lapsed().lapsed
    assert renewal_done.wait(timeout=2.0)

    # conn was lapsed at the one instant the atomic sweep decided -- reaping
    # it is correct. The renewal, locked out until the sweep released the
    # lock, then lands as an ordinary fresh contact -- never silently lost.
    assert conn in reaped
    assert conn in reg.sessions()


def test_continuous_renewal_prevents_lease_lapse() -> None:
    """LR1: a connection that keeps renewing is never a candidate for lapsing."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _writes(reg).record(conn, _cli(), UNOBSERVED)

    for _ in range(5):
        clock.advance(60.0)  # inside the 90s cli lease if renewed each time
        _writes(reg).record(conn, None, UNOBSERVED)  # a bare contact renews

    assert _writes(reg).reap_lapsed().lapsed == frozenset()
    assert conn in reg.sessions()


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def _mcp() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


@final
class _Leg:
    """A listen leg stand-in. Its object identity is the whole ownership test."""

    def wake(self) -> None:
        """Delivery is the router's; these tests are about who holds the slot."""


def _attached(
    reg: HubClientRegistry, conn: ConnectionId, identity: ClientIdentity
) -> _Leg:
    """Connect a leg for ``conn`` and return it — the token every write compares to."""
    leg = _Leg()
    _writes(reg).attach(conn, identity, leg, UNOBSERVED)
    return leg


def test_register_callback_stores_it_on_an_identified_session() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _attached(reg, conn, _mcp())
    assert _writes(reg).register_callback(conn, _beads()).outcome == "registered"
    assert reg.sessions()[conn].callbacks == (_beads(),)


def test_register_callback_refuses_an_unknown_session() -> None:
    reg = HubClientRegistry()
    outcome = _writes(reg).register_callback(ConnectionId("never"), _beads()).outcome
    assert outcome == "superseded"


def test_register_callback_refuses_a_lapsed_session() -> None:
    """A leg still installed does not make a session that stopped renewing eligible."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _attached(reg, conn, _cli())
    clock.advance(91.0)  # past the 90s cli lease
    assert _writes(reg).register_callback(conn, _beads()).outcome == "declined"
    assert reg.sessions()[conn].callbacks == ()


def test_a_registration_gated_against_a_departed_leg_is_refused() -> None:
    """The gate and the write are separate moments; the leg may go between them.

    Committing anyway leaves a menu item with no listener — and, because the
    withdrawal that would have removed it has already run, nothing that will ever
    remove it. The user gets an entry that swallows every click.
    """
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    leg = _attached(reg, conn, _mcp())
    assert (
        _writes(reg).detach(conn, leg).outcome == "released"
    )  # the leg tore down meanwhile

    assert _writes(reg).register_callback(conn, _beads()).outcome == "superseded"
    assert reg.sessions()[conn].callbacks == ()


def test_a_registration_lands_on_the_leg_that_now_holds_the_connection() -> None:
    """A reconnect of the same identity resolves to the same connection.

    The write reads the slot it writes under the same hold, so there is no earlier
    leg for it to be stale against: the entry belongs to whichever session holds
    the connection when the write lands.
    """
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _attached(reg, conn, _mcp())
    successor = _attached(reg, conn, _mcp())  # the successor takes the connection

    assert _writes(reg).register_callback(conn, _beads()).outcome == "registered"
    assert reg.sessions()[conn].held_by(successor)
    assert reg.sessions()[conn].callbacks == (_beads(),)


def test_registering_the_same_id_replaces_the_earlier_callback() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _attached(reg, conn, _mcp())
    _writes(reg).register_callback(conn, SessionCallback(id="beads", label="Beads"))
    _writes(reg).register_callback(
        conn, SessionCallback(id="beads", label="Beads Browser")
    )
    callbacks = reg.sessions()[conn].callbacks
    assert callbacks == (SessionCallback(id="beads", label="Beads Browser"),)


def test_a_new_leg_starts_with_none_of_its_predecessors_callbacks() -> None:
    """Two sessions of one identity may be live at once, and the id is shared.

    Leaving the callbacks would keep the predecessor's entries in the bar with
    every click routed to the newcomer — reachable with no interleaving at all,
    just a connect. Nothing else would withdraw them, because the session that
    could has lost the slot.
    """
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _attached(reg, conn, _mcp())
    _writes(reg).register_callback(conn, _beads())
    assert reg.sessions()[conn].callbacks == (_beads(),)

    second = _Leg()
    # The arriving session is told it cleared entries, because that is what makes
    # the bar wrong and nothing else is guaranteed to correct it.
    assert (
        _writes(reg).attach(conn, _mcp(), second, UNOBSERVED).slot
        == "attached_over_callbacks"
    )

    assert reg.sessions()[conn].callbacks == ()
    assert reg.sessions()[conn].held_by(second)


def test_a_first_leg_clears_nothing_and_says_so() -> None:
    """An empty slot has no entries to lose, so the bar is already right."""
    reg = HubClientRegistry()
    app = ClientIdentity(kind="app", name="voxd", repo="/w/vox")
    assert (
        _writes(reg).attach(ConnectionId("app"), app, _Leg(), UNOBSERVED).slot
        == "attached"
    )


def test_a_teardown_by_a_session_that_lost_the_slot_removes_nothing() -> None:
    """The stale teardown: a suspended predecessor must not strip its successor.

    The predecessor sits in its finally awaiting a cancelled writer while the
    reconnect completes an entire connect. Unguarded, it then removes the
    successor's leg and callbacks — and the successor keeps renewing its lease,
    so no sweep ever repairs it. It stays live, believing it is push-reachable,
    owning nothing.
    """
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    stale = _attached(reg, conn, _mcp())
    successor = _attached(reg, conn, _mcp())
    _writes(reg).register_callback(conn, _beads())

    assert _writes(reg).detach(conn, stale).outcome == "kept"

    assert reg.sessions()[conn].held_by(successor)
    assert reg.sessions()[conn].callbacks == (_beads(),)


def test_a_teardown_releases_the_leg_and_its_callbacks_together() -> None:
    """Never one without the other: the gap between two writes is observable.

    Clicks route and registrations commit on other threads, so a moment in which
    a callback is present and its leg is gone is a moment one of them can read.
    """
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    leg = _attached(reg, conn, _mcp())
    _writes(reg).register_callback(conn, _beads())

    assert _writes(reg).detach(conn, leg).outcome == "released_with_callbacks"

    session = reg.sessions()[conn]
    assert session.callbacks == ()
    assert session.is_push_reachable is False
    assert session.identity is not None  # the session itself survives the leg


def test_a_teardown_after_a_departure_is_a_release_not_a_keep() -> None:
    """The two ways to not hold the slot are not the same answer.

    A departure (the atomic deregister-and-release coordinator, run here
    directly as ``discard``) takes the session, its slot, and its entries
    while its socket is still winding down — a lapsed lease alone, merely
    read, never does this (reads remove no one). When that socket's teardown
    finally runs there is nothing of anyone's left in the registry to
    remove — but nobody holds the connection either, and the bar is still
    showing entries whose owner departed. Answering ``kept`` there says a
    successor's entries are live, which is false, and leaves them on screen.
    """
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    leg = _attached(reg, conn, _cli())
    _writes(reg).register_callback(conn, _beads())
    clock.advance(91.0)  # past the 90s cli lease
    assert reg.live_sessions() == {}  # a read: filtered, not removed
    _writes(reg).discard(conn)  # the departure the background reap timer performs

    assert _writes(reg).detach(conn, leg).outcome == "released_with_session"


def test_a_teardown_that_removed_no_entries_asks_for_no_menu_push() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    leg = _attached(reg, conn, _mcp())
    assert _writes(reg).detach(conn, leg).outcome == "released"


def test_an_identified_connection_with_no_leg_refuses_a_registration() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _writes(reg).record(conn, _mcp(), UNOBSERVED)  # identified, nothing to push to

    assert _writes(reg).register_callback(conn, _beads()).outcome == "superseded"


def test_the_leg_and_its_callbacks_are_written_under_one_lock() -> None:
    """The property the whole fix rests on: nothing observes the write half-done.

    Instrumented rather than inferred from an outcome, in the shape the router's
    lock-order tests use. The clock is called inside the registry's critical
    section, so a probe fired from it runs at the exact moment the comparison has
    happened and the write has not. A non-reentrant lock that refuses a second
    acquire there is the lock still being held — so the compare and the write are
    one section, and the leg and the callbacks it governs are behind the same one.
    """
    held_during: list[bool] = []
    registry: list[HubClientRegistry] = []

    def _probing_clock() -> float:
        if registry:
            acquired = registry[0]._lock.acquire(blocking=False)
            held_during.append(not acquired)
            if acquired:
                registry[0]._lock.release()
        return 0.0

    reg = HubClientRegistry(_probing_clock)
    registry.append(reg)
    conn = ConnectionId("mcp")
    _attached(reg, conn, _mcp())
    assert _writes(reg).register_callback(conn, _beads()).outcome == "registered"

    assert held_during  # the probe ran
    assert all(held_during)  # and every write it caught was inside the lock


def test_a_lapsed_lease_departs_the_session_and_its_callbacks_together() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    _attached(reg, conn, _cli())
    _writes(reg).register_callback(conn, _beads())
    clock.advance(91.0)  # past the cli lease
    # A read only filters -- the session and its callbacks are still on paper.
    assert reg.live_sessions() == {}
    assert conn in reg.sessions()

    _writes(reg).discard(conn)  # the coordinator's atomic departure

    assert reg.sessions() == {}  # session and callbacks left in the same motion


def test_a_declared_ttl_lapses_an_app_session_that_would_be_permanent() -> None:
    # The dead-daemon story: an "app" kind is permanent by default, but a daemon
    # that DECLARES a short lease leaves the menu on that timer when it dies, with
    # no reconnect to renew.
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("voxd")
    identity = ClientIdentity(kind="app", name="voxd", lease_ttl=30.0)
    _attached(reg, conn, identity)
    _writes(reg).register_callback(conn, _beads())
    assert conn in reg.live_sessions()

    clock.advance(31.0)  # past the declared 30s lease, no contact in between
    assert reg.live_sessions() == {}  # filtered out of the live view
    assert conn in reg.sessions()  # still registered until actually departed


def test_an_undeclared_app_lease_stays_permanent() -> None:
    # luxd's built-ins declare no TTL, so they fall to the permanent app default and
    # never lapse — the "appear once and always work" items.
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("luxd")
    _writes(reg).record(conn, ClientIdentity(kind="app", name="luxd"), UNOBSERVED)
    clock.advance(1_000_000.0)
    assert conn in reg.live_sessions()


def test_a_declared_ttl_renews_on_contact_like_any_lease() -> None:
    # Any authenticated contact renews the declared lease, so a daemon that keeps in
    # touch within its cadence stays live.
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("voxd")
    identity = ClientIdentity(kind="app", name="voxd", lease_ttl=30.0)
    _writes(reg).record(conn, identity, UNOBSERVED)

    clock.advance(20.0)
    _writes(reg).record(conn, identity, UNOBSERVED)  # a renewal within the 30s window
    clock.advance(20.0)  # 40s from the start, but only 20s since the renewal
    assert conn in reg.live_sessions()


def test_discard_is_a_noop_when_absent() -> None:
    reg = HubClientRegistry()
    _writes(reg).discard(ConnectionId("never-registered"))
    assert reg.sessions() == {}


def test_concurrent_record_and_discard_against_iterating_sessions() -> None:
    reg = HubClientRegistry()
    conns = [ConnectionId(f"conn-{i}") for i in range(50)]
    stop = threading.Event()
    caught: list[threading.ExceptHookArgs] = []
    caught_lock = threading.Lock()

    def record(args: threading.ExceptHookArgs) -> None:
        with caught_lock:
            caught.append(args)

    writers = [
        threading.Thread(target=_churn, args=(reg, conns, stop)) for _ in range(4)
    ]
    readers = [threading.Thread(target=_read, args=(reg, stop)) for _ in range(4)]
    workers = writers + readers

    previous_hook = threading.excepthook
    threading.excepthook = record
    try:
        for worker in workers:
            worker.start()
        stop.wait(timeout=0.5)
        stop.set()
        for worker in workers:
            worker.join(timeout=2.0)
    finally:
        threading.excepthook = previous_hook

    # No thread raised — the reads stayed coherent under concurrent mutation.
    assert caught == [], [args.exc_value for args in caught]


@final
class _SlowIdentity(ClientIdentity):
    """An identity whose menu name takes a moment to read.

    Naming happens inside the registry's lock, and on a real identity that step is
    a few instructions wide. Widening it does not change what the registry does —
    it only makes the window a second thread would have to hit observable.
    """

    @property
    def menu_label(self) -> str:
        time.sleep(0.001)
        return super().menu_label


def _slow_mcp() -> ClientIdentity:
    """An mcp session in ``/w/lux`` whose menu name takes a moment to read."""
    return _SlowIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def test_a_named_client_keeps_its_name_across_reads() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _writes(reg).record(conn, _mcp(), UNOBSERVED)

    assert reg.named_sessions().name_of(conn, "client") == "lux"
    assert reg.named_sessions().name_of(conn, "client") == "lux"


def test_an_unidentified_session_is_live_but_unnamed() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("bare")
    _writes(reg).record(conn, None, UNOBSERVED)

    named = reg.named_sessions()

    assert conn in named.sessions
    assert named.name_of(conn, "client") == "client"


def test_a_lapsed_but_undeparted_session_keeps_its_name_reserved() -> None:
    """RD2: a read never frees a name — only an actual departure does.

    A lapsed lease alone does not release the roster entry: departure is
    told to the roster, never inferred by it, and a read tells it nothing.
    """
    clock = _Clock()
    reg = HubClientRegistry(clock)
    lapsing, arrival = ConnectionId("cli"), ConnectionId("later")
    _writes(reg).record(lapsing, _cli(), UNOBSERVED)
    assert reg.named_sessions().name_of(lapsing, "client") == "lux"

    clock.advance(91.0)  # past the 90s cli lease; nobody has departed lapsing
    _writes(reg).record(arrival, _cli(), UNOBSERVED)

    # lapsing still holds the base name — arrival is numbered against it.
    assert reg.named_sessions().name_of(arrival, "client") == "lux (2)"


def test_departing_a_lapsed_session_frees_its_name() -> None:
    """Once the coordinator actually departs the lapsed session, its name frees."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    lapsing, arrival = ConnectionId("cli"), ConnectionId("later")
    _writes(reg).record(lapsing, _cli(), UNOBSERVED)
    assert reg.named_sessions().name_of(lapsing, "client") == "lux"  # claims "lux"
    clock.advance(91.0)  # past the 90s cli lease
    _writes(reg).record(arrival, _cli(), UNOBSERVED)
    assert reg.named_sessions().name_of(arrival, "client") == "lux (2)"

    _writes(reg).discard(lapsing)  # the coordinator's atomic departure

    assert reg.named_sessions().name_of(arrival, "client") == "lux"  # the freed name


def test_discard_releases_the_name_with_the_session() -> None:
    reg = HubClientRegistry()
    departing, arrival = ConnectionId("first"), ConnectionId("second")
    _writes(reg).record(departing, _mcp(), UNOBSERVED)
    reg.named_sessions()

    _writes(reg).discard(departing)
    _writes(reg).record(arrival, _mcp(), UNOBSERVED)

    assert reg.named_sessions().name_of(arrival, "client") == "lux"


def test_the_survivor_keeps_its_number_until_the_first_actually_departs() -> None:
    """A lapse alone does not free the base name — only a departure does.

    A mere read discovering the lapse changes nothing (RD2): the survivor
    stays ``lux (2)`` until the coordinator (``discard``, here standing in
    for a graceful disconnect or the background reap timer) actually departs
    the lapsed connection, at which point the base name is theirs to inherit.
    """
    clock = _Clock()
    reg = HubClientRegistry(clock)
    lapsing, staying = ConnectionId("cli"), ConnectionId("mcp")
    _writes(reg).record(lapsing, _cli(), UNOBSERVED)
    _writes(reg).record(staying, _mcp(), UNOBSERVED)
    assert reg.named_sessions().name_of(staying, "client") == "lux (2)"

    clock.advance(91.0)  # the cli lease lapses; the mcp session's has 1800s
    assert reg.named_sessions().name_of(staying, "client") == "lux (2)"  # unchanged

    _writes(reg).discard(lapsing)  # the departure the timer or a disconnect performs

    assert reg.named_sessions().name_of(staying, "client") == "lux"


def test_the_survivor_takes_the_plain_name_when_the_first_is_discarded() -> None:
    """The live defect: a session restart overlaps the outgoing session's lease.

    The outgoing session still holds ``lux`` while owning no menu entry, so the
    arriving one is numbered against a ghost. When the ghost's disconnect cascade
    discards it the newcomer is alone, and a client alone wears no number.
    """
    reg = HubClientRegistry()
    outgoing, arriving = ConnectionId("old-session"), ConnectionId("new-session")
    _writes(reg).record(outgoing, _mcp(), UNOBSERVED)
    _writes(reg).record(arriving, _mcp(), UNOBSERVED)
    assert reg.named_sessions().name_of(arriving, "client") == "lux (2)"

    _writes(reg).discard(outgoing)

    assert reg.named_sessions().name_of(arriving, "client") == "lux"


def test_two_clients_that_are_both_here_keep_the_names_they_were_given() -> None:
    """Only a removal moves a name: reads and arrivals leave the bar as it is."""
    reg = HubClientRegistry()
    first, second = ConnectionId("first"), ConnectionId("second")
    _writes(reg).record(first, _mcp(), UNOBSERVED)
    _writes(reg).record(second, _mcp(), UNOBSERVED)
    assert reg.named_sessions().name_of(second, "client") == "lux (2)"

    _writes(reg).record(
        ConnectionId("third"), _mcp(), UNOBSERVED
    )  # a third arrives on the same repo

    named = reg.named_sessions()
    assert named.name_of(first, "client") == "lux"
    assert named.name_of(second, "client") == "lux (2)"


def test_a_name_survives_a_read_taken_while_another_client_arrives() -> None:
    """No reader can retire a name, so a slower one cannot undo a faster one's work.

    Each caller used to take its own picture of the live sessions and release
    whatever that picture did not show, so a reader holding the older picture
    dropped the name a newer read had just assigned — the menu and the details
    frame then disagreed about which client was ``lux (2)``. A caller now hands the
    registry nothing: the only picture is the registry's own store, read under its
    lock, and departures are stated by the step that removes a session.
    """
    reg = HubClientRegistry()
    conns = [ConnectionId(f"c{n}") for n in range(6)]
    for conn in conns:
        _writes(reg).record(conn, _slow_mcp(), UNOBSERVED)
    reads: list[list[str]] = []
    failures: list[BaseException] = []
    stop = threading.Event()

    def keep_reading() -> None:
        try:
            while not stop.is_set():
                named = reg.named_sessions()
                reads.append([named.name_of(conn, "MISSING") for conn in conns])
        except BaseException as exc:  # noqa: BLE001 — the thread's own boundary
            failures.append(exc)

    readers = [threading.Thread(target=keep_reading) for _ in range(4)]
    for reader in readers:
        reader.start()
    for late in range(6, 12):  # more clients arrive while the readers are inside
        _writes(reg).record(ConnectionId(f"c{late}"), _slow_mcp(), UNOBSERVED)
    stop.set()
    for reader in readers:
        reader.join(timeout=5.0)

    assert failures == [], f"a read raised: {failures[0]!r}"
    assert reads, "no read completed"
    for names in reads:
        assert "MISSING" not in names, f"a live client lost its name: {names}"
        assert len(set(names)) == len(names), f"a name was shared: {names}"


def test_record_reports_a_new_agent_as_gained_and_a_repeat_as_unchanged() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")

    assert _writes(reg).record(conn, _mcp(), UNOBSERVED).presence == "gained"
    assert _writes(reg).record(conn, _mcp(), UNOBSERVED).presence == "unchanged"


def test_record_reports_a_changed_declaration_as_revised() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    _writes(reg).record(conn, _mcp(), UNOBSERVED)

    other = ClientIdentity(kind="mcp-session", name="claude", repo="/w/other")

    assert _writes(reg).record(conn, other, UNOBSERVED).presence == "revised"


def test_record_reports_a_lapsed_agents_renewal_as_gained() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("mcp")
    _writes(reg).record(conn, _mcp(), UNOBSERVED)
    clock.advance(1_000_000.0)  # lapsed; nothing has swept it

    assert _writes(reg).record(conn, None, UNOBSERVED).presence == "gained"


_TAKEN: dict[int, tuple[HubClientRegistry, PresenceWrites]] = {}


def _writes(reg: HubClientRegistry) -> PresenceWrites:
    """The registry's listener legs, taken once as the lifecycle would take them."""
    if id(reg) not in _TAKEN:
        _TAKEN[id(reg)] = (reg, reg.take_writes())
    return _TAKEN[id(reg)][1]


def _presence(write: SessionWrite | None) -> str:
    """The presence change of a renewal that found its session."""
    assert write is not None
    return write.presence


def test_renew_if_registered_reports_a_revival_and_never_registers() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("mcp")
    assert _writes(reg).renew_if_registered(conn, UNOBSERVED) is None
    assert reg.sessions() == {}

    _writes(reg).record(conn, _mcp(), UNOBSERVED)
    assert _presence(_writes(reg).renew_if_registered(conn, UNOBSERVED)) == "unchanged"
    clock.advance(1_000_000.0)

    assert _presence(_writes(reg).renew_if_registered(conn, UNOBSERVED)) == "gained"


def test_attaching_over_callbacks_revises_the_menu_though_presence_held() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("app")
    app = ClientIdentity(kind="app", name="voxd", repo="/w/vox")
    _attached(reg, conn, app)
    _writes(reg).register_callback(conn, _beads())

    attachment = _writes(reg).attach(conn, app, _Leg(), UNOBSERVED)

    assert attachment.slot == "attached_over_callbacks"
    assert attachment.presence == "revised"


def _lux(session: str) -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name=session, repo="/w/lux")


class TestDepartureReportsWhoseNameMoved:
    def test_discard_reports_the_survivor_that_inherits_the_base_name(self) -> None:
        reg = HubClientRegistry()
        first, second = ConnectionId("first"), ConnectionId("second")
        _writes(reg).record(first, _lux("a"), UNOBSERVED)
        _writes(reg).record(second, _lux("b"), UNOBSERVED)
        reg.named_sessions()  # the read that names them: lux, lux (2)

        assert _writes(reg).discard(first) == frozenset({second})

    def test_discard_of_a_junior_moves_nobody(self) -> None:
        reg = HubClientRegistry()
        first, second = ConnectionId("first"), ConnectionId("second")
        _writes(reg).record(first, _lux("a"), UNOBSERVED)
        _writes(reg).record(second, _lux("b"), UNOBSERVED)
        reg.named_sessions()

        assert _writes(reg).discard(second) == frozenset()

    def test_discard_of_an_unknown_connection_moves_nobody(self) -> None:
        assert (
            _writes(HubClientRegistry()).discard(ConnectionId("ghost")) == frozenset()
        )

    def test_a_sweep_reports_both_who_lapsed_and_whose_name_moved(self) -> None:
        clock = _Clock()
        reg = HubClientRegistry(clock)
        lapsing, staying = ConnectionId("lapsing"), ConnectionId("staying")
        _writes(reg).record(
            lapsing,
            ClientIdentity(kind="cli", name="x", repo="/w/elsewhere"),
            UNOBSERVED,
        )  # its own name: shares nothing
        _writes(reg).record(staying, _mcp(), UNOBSERVED)
        reg.named_sessions()
        clock.advance(91.0)

        reaped = _writes(reg).reap_lapsed()

        assert reaped.lapsed == frozenset({lapsing})
        assert reaped.relabelled == frozenset()

    def test_a_sweep_that_frees_a_shared_base_name_relabels_the_survivor(self) -> None:
        clock = _Clock()
        reg = HubClientRegistry(clock)
        first, second = ConnectionId("first"), ConnectionId("second")
        _writes(reg).record(
            first, ClientIdentity(kind="cli", name="a", repo="/w/lux"), UNOBSERVED
        )
        _writes(reg).record(second, _lux("b"), UNOBSERVED)
        reg.named_sessions()  # first = lux, second = lux (2)
        clock.advance(91.0)  # the cli lapses; the mcp lease survives
        _writes(reg).record(second, None, UNOBSERVED)  # a contact renews the survivor

        reaped = _writes(reg).reap_lapsed()

        assert reaped.lapsed == frozenset({first})
        assert reaped.relabelled == frozenset({second})
