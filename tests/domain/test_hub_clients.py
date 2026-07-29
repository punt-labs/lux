"""HubClientRegistry — session roster reads and writes are serialized.

Bind, identify, and unbind run on the transport's connection threads while
``list_clients`` reads on a tool thread, so every access to the roster is
guarded by the registry's lock. These tests exercise the ``record`` upsert (bare
registration and identity declaration are the same primitive), the repository
projection, and hammer the registry from many threads to prove the reads stay
coherent and no thread raises.
"""

from __future__ import annotations

import threading

from punt_lux.domain.hub.client_identity import ClientIdentity, ClientSession
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.ids import ConnectionId


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
