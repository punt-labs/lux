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

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.session_callback import SessionCallback
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
            reg.record(conn)
        for conn in conns:
            reg.discard(conn)


def _read(reg: HubClientRegistry, stop: threading.Event) -> None:
    """Snapshot the roster until told to stop; every value is a session record."""
    while not stop.is_set():
        for value in reg.sessions().values():
            assert isinstance(value, ClientSession)


def test_record_is_idempotent_and_stamps_once() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    reg.record(conn)
    first = reg.sessions()[conn].connected_at
    reg.record(conn)
    # A re-record keeps the original connect time — age never resets.
    assert reg.sessions()[conn].connected_at == first


def test_a_bare_record_leaves_the_session_unidentified() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    reg.record(conn)
    assert reg.sessions()[conn].identity is None


def test_record_with_identity_keeps_the_connect_time() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    reg.record(conn)
    stamped = reg.sessions()[conn].connected_at

    identity = ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")
    reg.record(conn, identity)

    session = reg.sessions()[conn]
    assert session.identity == identity
    # Declaring an identity records who, not when — the age is unchanged.
    assert session.connected_at == stamped


def test_a_later_bare_record_never_drops_a_declared_identity() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    reg.record(conn, identity)
    # The connect path re-records without an identity; the declaration survives.
    reg.record(conn)
    assert reg.sessions()[conn].identity == identity


def test_record_with_identity_registers_an_unseen_connection() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    assert reg.session_of(conn) is None
    reg.record(conn, ClientIdentity(kind="cli", name="lux-cli"))
    assert reg.session_of(conn) is not None  # membership via the O(1) session read
    assert reg.sessions()[conn].identity is not None


def test_session_of_returns_the_record_or_none() -> None:
    reg = HubClientRegistry()
    identified = ConnectionId("identified")
    bare = ConnectionId("bare")
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    reg.record(identified, identity)
    reg.record(bare)
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
    reg.record(conn, ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux"))
    reg.discard(conn)
    assert reg.sessions() == {}


def test_repos_projects_the_distinct_declared_repositories() -> None:
    reg = HubClientRegistry()
    reg.record(ConnectionId("a"), ClientIdentity(kind="cli", name="lux", repo="/w/lux"))
    reg.record(ConnectionId("b"), ClientIdentity(kind="cli", name="vox", repo="/w/vox"))
    # A second session in an already-listed repo does not double it.
    reg.record(
        ConnectionId("c"),
        ClientIdentity(
            kind="mcp-session", name="claude", repo="/w/lux", agent="claude"
        ),
    )
    assert reg.repos() == frozenset({"/w/lux", "/w/vox"})


def test_repos_excludes_headless_and_unidentified_sessions() -> None:
    reg = HubClientRegistry()
    reg.record(ConnectionId("unidentified"))
    reg.record(ConnectionId("headless"), ClientIdentity(kind="cli", name="lux-cli"))
    reg.record(ConnectionId("app"), ClientIdentity(kind="app", name="lux"))
    assert reg.repos() == frozenset()


def _cli(name: str = "lux") -> ClientIdentity:
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def test_live_sessions_filters_an_expired_session_without_sweeping_it() -> None:
    """RD1: a read filters the live view; it never removes the registry entry."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    assert conn in reg.live_sessions()

    clock.advance(91.0)  # past the 90s cli lease
    assert reg.live_sessions() == {}  # filtered out of the live view
    assert conn in reg.sessions()  # still registered — the read removed no one


def test_any_contact_renews_the_lease() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())

    clock.advance(80.0)
    reg.record(conn)  # a bare contact renews, keeping the declared identity
    clock.advance(80.0)  # 160s from the start, but only 80s since the renewal

    live = reg.live_sessions()
    assert conn in live  # still inside the 90s window from the renewal
    assert live[conn].identity == _cli()


def test_an_mcp_session_outlives_a_cli_session() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    cli, mcp = ConnectionId("cli"), ConnectionId("mcp")
    reg.record(cli, _cli())
    reg.record(mcp, ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux"))

    clock.advance(120.0)  # past the cli lease (90s), well within the mcp lease (1800s)
    live = reg.live_sessions()
    assert cli not in live
    assert mcp in live


def test_no_read_ever_removes_a_lapsed_session() -> None:
    """RD1: neither the raw read nor the live read sweeps a lapsed entry."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    clock.advance(91.0)
    assert conn in reg.sessions()
    reg.live_sessions()  # a read; still non-destructive
    assert conn in reg.sessions()
    reg.named_sessions()  # a read; still non-destructive
    assert conn in reg.sessions()


def test_reap_lapsed_locked_returns_who_lapsed_and_removes_only_them() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    lapsing, staying = ConnectionId("cli"), ConnectionId("mcp")
    reg.record(lapsing, _cli())
    reg.record(staying, _mcp())

    clock.advance(91.0)  # past the cli lease; the mcp lease (1800s) survives

    assert reg.reap_lapsed_locked() == frozenset({lapsing})
    assert lapsing not in reg.sessions()  # actually removed, not just filtered
    assert staying in reg.sessions()


def test_reap_lapsed_locked_is_empty_and_a_no_op_when_nothing_has_lapsed() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    reg.record(conn, _cli())
    assert reg.reap_lapsed_locked() == frozenset()
    assert conn in reg.sessions()


def test_reap_lapsed_locked_honors_its_exclusion() -> None:
    """The exclusion ``apply``'s renewed caller needs, at the registry layer."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    clock.advance(91.0)  # past the 90s cli lease

    assert reg.reap_lapsed_locked(exclude=frozenset({conn})) == frozenset()
    assert conn in reg.sessions()  # excluded, so left alone
    assert reg.reap_lapsed_locked() == frozenset({conn})
    assert conn not in reg.sessions()


def test_reap_lapsed_locked_cannot_wipe_a_renewal_that_races_it() -> None:
    """The TOCTOU a split compute-then-discard leaves open, closed by one lock.

    A round-1-era renewal path (``record``/``renew_if_registered``/
    ``attach_listener``) takes only the registry's own lock, not the Hub's
    ``StoreLock`` a departure sweep holds. A sweep that computes the lapsed
    set in one lock hold and discards each id in a second, separate hold
    leaves a gap: a renewal landing in that gap makes the connection live
    again, and the second hold discards it anyway -- a live client silently
    wiped under ordinary threaded load. ``reap_lapsed_locked`` closes the
    gap by construction: nothing else can touch the registry while it
    holds the lock, so a concurrent renewal is strictly serialized before
    or after the sweep, never straddling it.
    """
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    clock.advance(91.0)  # past the 90s cli lease

    renewal_attempted = threading.Event()
    renewal_done = threading.Event()

    def _renew_concurrently() -> None:
        renewal_attempted.set()
        reg.record(conn)  # blocks on the registry's own lock until reap yields
        renewal_done.set()

    real_now = reg._clock

    def _now_that_races_a_renewal() -> float:
        # Fires from inside reap_lapsed_locked's one critical section: start
        # the renewal thread and prove it is genuinely locked out (blocked on
        # the same lock, not just "hasn't run yet") before the sweep proceeds.
        if not renewal_attempted.is_set():
            threading.Thread(target=_renew_concurrently, daemon=True).start()
            assert renewal_attempted.wait(timeout=2.0)
            time.sleep(0.05)  # give the renewal thread time to reach lock.acquire()
            assert not renewal_done.is_set()
        return real_now()

    reg._clock = _now_that_races_a_renewal

    reaped = reg.reap_lapsed_locked()
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
    reg.record(conn, _cli())

    for _ in range(5):
        clock.advance(60.0)  # inside the 90s cli lease if renewed each time
        reg.record(conn)  # a bare contact renews

    assert reg.reap_lapsed_locked() == frozenset()
    assert conn in reg.sessions()


def test_repos_excludes_a_session_whose_lease_lapsed() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    reg.record(ConnectionId("cli"), _cli())
    assert reg.repos() == frozenset({"/w/lux"})
    clock.advance(91.0)
    assert reg.repos() == frozenset()  # the lapsed session drops from live-context


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
    reg.attach_listener(conn, identity, leg)
    return leg


def test_register_callback_stores_it_on_an_identified_session() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    leg = _attached(reg, conn, _mcp())
    assert reg.register_callback(conn, _beads(), leg) == "registered"
    assert reg.sessions()[conn].callbacks == (_beads(),)


def test_register_callback_refuses_an_unknown_session() -> None:
    reg = HubClientRegistry()
    outcome = reg.register_callback(ConnectionId("never"), _beads(), _Leg())
    assert outcome == "superseded"


def test_register_callback_refuses_a_lapsed_session() -> None:
    """A leg still installed does not make a session that stopped renewing eligible."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    leg = _attached(reg, conn, _cli())
    clock.advance(91.0)  # past the 90s cli lease
    assert reg.register_callback(conn, _beads(), leg) == "declined"
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
    assert reg.detach_listener(conn, leg) == "released"  # the leg tore down meanwhile

    assert reg.register_callback(conn, _beads(), leg) == "superseded"
    assert reg.sessions()[conn].callbacks == ()


def test_a_registration_gated_against_a_replaced_leg_is_refused() -> None:
    """The same window, closed by a successor rather than by a teardown.

    A reconnect of the same identity resolves to the same connection, so the leg
    the caller was gated against can be replaced rather than removed. Its entry
    would then belong to a session that never asked for it, and its clicks would
    be pushed to the newcomer.
    """
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    first = _attached(reg, conn, _mcp())
    _attached(reg, conn, _mcp())  # the successor takes the connection

    assert reg.register_callback(conn, _beads(), first) == "superseded"
    assert reg.sessions()[conn].callbacks == ()


def test_registering_the_same_id_replaces_the_earlier_callback() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    leg = _attached(reg, conn, _mcp())
    reg.register_callback(conn, SessionCallback(id="beads", label="Beads"), leg)
    reg.register_callback(conn, SessionCallback(id="beads", label="Beads Browser"), leg)
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
    first = _attached(reg, conn, _mcp())
    reg.register_callback(conn, _beads(), first)
    assert reg.sessions()[conn].callbacks == (_beads(),)

    second = _Leg()
    # The arriving session is told it cleared entries, because that is what makes
    # the bar wrong and nothing else is guaranteed to correct it.
    assert reg.attach_listener(conn, _mcp(), second) == "attached_over_callbacks"

    assert reg.sessions()[conn].callbacks == ()
    assert reg.sessions()[conn].held_by(second)


def test_a_first_leg_clears_nothing_and_says_so() -> None:
    """An empty slot has no entries to lose, so the bar is already right."""
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    assert reg.attach_listener(conn, _mcp(), _Leg()) == "attached"


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
    reg.register_callback(conn, _beads(), successor)

    assert reg.detach_listener(conn, stale) == "kept"

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
    reg.register_callback(conn, _beads(), leg)

    assert reg.detach_listener(conn, leg) == "released_with_callbacks"

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
    reg.register_callback(conn, _beads(), leg)
    clock.advance(91.0)  # past the 90s cli lease
    assert reg.live_sessions() == {}  # a read: filtered, not removed
    reg.discard(conn)  # the departure the background reap timer performs

    assert reg.detach_listener(conn, leg) == "released_with_session"


def test_a_teardown_that_removed_no_entries_asks_for_no_menu_push() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    leg = _attached(reg, conn, _mcp())
    assert reg.detach_listener(conn, leg) == "released"


def test_the_leg_read_is_what_the_gate_asks() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    reg.record(conn, _mcp())
    assert reg.listener_of(conn) is None  # identified, but nothing to push to

    leg = _attached(reg, conn, _mcp())
    assert reg.listener_of(conn) is leg


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
    leg = _attached(reg, conn, _mcp())
    assert reg.register_callback(conn, _beads(), leg) == "registered"

    assert held_during  # the probe ran
    assert all(held_during)  # and every write it caught was inside the lock


def test_a_lapsed_lease_departs_the_session_and_its_callbacks_together() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    leg = _attached(reg, conn, _cli())
    reg.register_callback(conn, _beads(), leg)
    clock.advance(91.0)  # past the cli lease
    # A read only filters -- the session and its callbacks are still on paper.
    assert reg.live_sessions() == {}
    assert conn in reg.sessions()

    reg.discard(conn)  # the coordinator's atomic departure

    assert reg.sessions() == {}  # session and callbacks left in the same motion


def test_a_declared_ttl_lapses_an_app_session_that_would_be_permanent() -> None:
    # The dead-daemon story: an "app" kind is permanent by default, but a daemon
    # that DECLARES a short lease leaves the menu on that timer when it dies, with
    # no reconnect to renew.
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("voxd")
    identity = ClientIdentity(kind="app", name="voxd", lease_ttl=30.0)
    leg = _attached(reg, conn, identity)
    reg.register_callback(conn, _beads(), leg)
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
    reg.record(conn, ClientIdentity(kind="app", name="luxd"))
    clock.advance(1_000_000.0)
    assert conn in reg.live_sessions()


def test_a_declared_ttl_renews_on_contact_like_any_lease() -> None:
    # Any authenticated contact renews the declared lease, so a daemon that keeps in
    # touch within its cadence stays live.
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("voxd")
    identity = ClientIdentity(kind="app", name="voxd", lease_ttl=30.0)
    reg.record(conn, identity)

    clock.advance(20.0)
    reg.record(conn, identity)  # a renewal within the 30s window
    clock.advance(20.0)  # 40s from the start, but only 20s since the renewal
    assert conn in reg.live_sessions()


def test_discard_is_a_noop_when_absent() -> None:
    reg = HubClientRegistry()
    reg.discard(ConnectionId("never-registered"))
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
    reg.record(conn, _mcp())

    assert reg.named_sessions().name_of(conn, "client") == "lux"
    assert reg.named_sessions().name_of(conn, "client") == "lux"


def test_an_unidentified_session_is_live_but_unnamed() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("bare")
    reg.record(conn)

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
    reg.record(lapsing, _cli())
    assert reg.named_sessions().name_of(lapsing, "client") == "lux"

    clock.advance(91.0)  # past the 90s cli lease; nobody has departed lapsing
    reg.record(arrival, _cli())

    # lapsing still holds the base name — arrival is numbered against it.
    assert reg.named_sessions().name_of(arrival, "client") == "lux (2)"


def test_departing_a_lapsed_session_frees_its_name() -> None:
    """Once the coordinator actually departs the lapsed session, its name frees."""
    clock = _Clock()
    reg = HubClientRegistry(clock)
    lapsing, arrival = ConnectionId("cli"), ConnectionId("later")
    reg.record(lapsing, _cli())
    assert reg.named_sessions().name_of(lapsing, "client") == "lux"  # claims "lux"
    clock.advance(91.0)  # past the 90s cli lease
    reg.record(arrival, _cli())
    assert reg.named_sessions().name_of(arrival, "client") == "lux (2)"

    reg.discard(lapsing)  # the coordinator's atomic departure

    assert reg.named_sessions().name_of(arrival, "client") == "lux"  # the freed name


def test_discard_releases_the_name_with_the_session() -> None:
    reg = HubClientRegistry()
    departing, arrival = ConnectionId("first"), ConnectionId("second")
    reg.record(departing, _mcp())
    reg.named_sessions()

    reg.discard(departing)
    reg.record(arrival, _mcp())

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
    reg.record(lapsing, _cli())
    reg.record(staying, _mcp())
    assert reg.named_sessions().name_of(staying, "client") == "lux (2)"

    clock.advance(91.0)  # the cli lease lapses; the mcp session's has 1800s
    assert reg.named_sessions().name_of(staying, "client") == "lux (2)"  # unchanged

    reg.discard(lapsing)  # the departure the timer or a disconnect performs

    assert reg.named_sessions().name_of(staying, "client") == "lux"


def test_the_survivor_takes_the_plain_name_when_the_first_is_discarded() -> None:
    """The live defect: a session restart overlaps the outgoing session's lease.

    The outgoing session still holds ``lux`` while owning no menu entry, so the
    arriving one is numbered against a ghost. When the ghost's disconnect cascade
    discards it the newcomer is alone, and a client alone wears no number.
    """
    reg = HubClientRegistry()
    outgoing, arriving = ConnectionId("old-session"), ConnectionId("new-session")
    reg.record(outgoing, _mcp())
    reg.record(arriving, _mcp())
    assert reg.named_sessions().name_of(arriving, "client") == "lux (2)"

    reg.discard(outgoing)

    assert reg.named_sessions().name_of(arriving, "client") == "lux"


def test_two_clients_that_are_both_here_keep_the_names_they_were_given() -> None:
    """Only a removal moves a name: reads and arrivals leave the bar as it is."""
    reg = HubClientRegistry()
    first, second = ConnectionId("first"), ConnectionId("second")
    reg.record(first, _mcp())
    reg.record(second, _mcp())
    assert reg.named_sessions().name_of(second, "client") == "lux (2)"

    reg.record(ConnectionId("third"), _mcp())  # a third arrives on the same repo

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
        reg.record(conn, _slow_mcp())
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
        reg.record(ConnectionId(f"c{late}"), _slow_mcp())
    stop.set()
    for reader in readers:
        reader.join(timeout=5.0)

    assert failures == [], f"a read raised: {failures[0]!r}"
    assert reads, "no read completed"
    for names in reads:
        assert "MISSING" not in names, f"a live client lost its name: {names}"
        assert len(set(names)) == len(names), f"a name was shared: {names}"
