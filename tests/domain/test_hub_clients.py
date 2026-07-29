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


def test_live_sessions_filters_and_sweeps_an_expired_session() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    assert conn in reg.live_sessions()

    clock.advance(91.0)  # past the 90s cli lease
    assert reg.live_sessions() == {}  # filtered out
    assert reg.sessions() == {}  # and swept from the store on the live read


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


def test_sessions_read_does_not_sweep_until_a_live_read() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    clock.advance(91.0)
    # The raw read carries no lease filter, so the lapsed entry is still present.
    assert conn in reg.sessions()
    reg.live_sessions()  # the live read is what reaps it
    assert conn not in reg.sessions()


def test_repos_excludes_a_session_whose_lease_lapsed() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    reg.record(ConnectionId("cli"), _cli())
    assert reg.repos() == frozenset({"/w/lux"})
    clock.advance(91.0)
    assert reg.repos() == frozenset()  # the lapsed session drops from live-context


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def test_register_callback_stores_it_on_an_identified_session() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    reg.record(conn, ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux"))
    assert reg.register_callback(conn, _beads()) is True
    assert reg.sessions()[conn].callbacks == (_beads(),)


def test_register_callback_refuses_an_unidentified_session() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("bare")
    reg.record(conn)  # bound but no identity declared
    assert reg.register_callback(conn, _beads()) is False
    assert reg.sessions()[conn].callbacks == ()


def test_register_callback_refuses_an_unknown_session() -> None:
    reg = HubClientRegistry()
    assert reg.register_callback(ConnectionId("never"), _beads()) is False


def test_register_callback_refuses_a_lapsed_session() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    clock.advance(91.0)  # past the 90s cli lease
    assert reg.register_callback(conn, _beads()) is False


def test_registering_the_same_id_replaces_the_earlier_callback() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("mcp")
    reg.record(conn, ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux"))
    reg.register_callback(conn, SessionCallback(id="beads", label="Beads"))
    reg.register_callback(conn, SessionCallback(id="beads", label="Beads Browser"))
    callbacks = reg.sessions()[conn].callbacks
    assert callbacks == (SessionCallback(id="beads", label="Beads Browser"),)


def test_a_lapsed_lease_sweeps_the_session_and_its_callbacks_together() -> None:
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    reg.record(conn, _cli())
    reg.register_callback(conn, _beads())
    clock.advance(91.0)  # past the cli lease
    # The live read sweeps the session; its callbacks leave in the same motion.
    assert reg.live_sessions() == {}
    assert reg.sessions() == {}


def test_a_declared_ttl_lapses_an_app_session_that_would_be_permanent() -> None:
    # The dead-daemon story: an "app" kind is permanent by default, but a daemon
    # that DECLARES a short lease leaves the menu on that timer when it dies, with
    # no reconnect to renew.
    clock = _Clock()
    reg = HubClientRegistry(clock)
    conn = ConnectionId("voxd")
    reg.record(conn, ClientIdentity(kind="app", name="voxd", lease_ttl=30.0))
    reg.register_callback(conn, _beads())
    assert conn in reg.live_sessions()

    clock.advance(31.0)  # past the declared 30s lease, no contact in between
    assert reg.live_sessions() == {}  # the session and its callback withdrew
    assert reg.sessions() == {}


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
