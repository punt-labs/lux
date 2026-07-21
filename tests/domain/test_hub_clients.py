"""HubClientRegistry — session roster reads and writes are serialized.

Bind and unbind run on the transport's connection threads while
``list_clients`` reads on a tool thread, so every access to the roster is
guarded by the registry's lock. These tests hammer the registry from many
threads at once and assert the reads stay coherent and no thread raises.
"""

from __future__ import annotations

import threading

from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.ids import ConnectionId


def _churn(
    reg: HubClientRegistry, conns: list[ConnectionId], stop: threading.Event
) -> None:
    """Register then discard every connection until told to stop."""
    while not stop.is_set():
        for conn in conns:
            reg.register(conn)
        for conn in conns:
            reg.discard(conn)


def _read(reg: HubClientRegistry, stop: threading.Event) -> None:
    """Snapshot the roster until told to stop; every value is a connect time."""
    while not stop.is_set():
        for value in reg.sessions().values():
            assert isinstance(value, float)


def test_register_is_idempotent_and_stamps_once() -> None:
    reg = HubClientRegistry()
    conn = ConnectionId("conn")
    reg.register(conn)
    first = reg.sessions()[conn]
    reg.register(conn)
    # A re-register keeps the original connect time — age never resets.
    assert reg.sessions()[conn] == first


def test_discard_is_a_noop_when_absent() -> None:
    reg = HubClientRegistry()
    reg.discard(ConnectionId("never-registered"))
    assert reg.sessions() == {}


def test_concurrent_register_and_discard_against_iterating_sessions() -> None:
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
