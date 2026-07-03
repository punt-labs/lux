"""InMemoryConnection — paired-queue duplex for in-process tests.

The in-memory backend lets tests drive both ends of a duplex without
crossing a real socket. ``paired()`` returns the two ends already wired
so a
single test fixture can simulate hub and client in one process.
"""

from __future__ import annotations

import threading

import pytest

from punt_lux.protocol.in_memory_connection import InMemoryConnection


def test_paired_send_round_trips_in_both_directions() -> None:
    a, b = InMemoryConnection.paired()
    a.send_line({"from": "a", "n": 1})
    b.send_line({"from": "b", "n": 2})

    a_recv = next(iter(a.iter_lines()))
    b_recv = next(iter(b.iter_lines()))

    a.close()
    b.close()
    assert a_recv == {"from": "b", "n": 2}
    assert b_recv == {"from": "a", "n": 1}


def test_iter_lines_returns_when_peer_closes() -> None:
    a, b = InMemoryConnection.paired()
    a.send_line({"first": True})
    a.close()

    received = list(b.iter_lines())

    b.close()
    assert received == [{"first": True}]


def test_send_after_close_raises() -> None:
    a, b = InMemoryConnection.paired()
    a.close()

    with pytest.raises(RuntimeError, match="send on closed"):
        a.send_line({"op": "noop"})

    b.close()


def test_send_after_peer_close_raises() -> None:
    """Writing to a peer that already called ``close`` must raise.

    Regression: previously, ``send_line`` only checked the
    local ``_closed`` flag, so a still-open end could enqueue frames
    onto a queue no one would ever drain — the equivalent of writing
    to a closed socket and getting silent success.
    """
    a, b = InMemoryConnection.paired()
    b.close()

    with pytest.raises(RuntimeError, match="peer closed"):
        a.send_line({"op": "noop"})

    a.close()


def test_symmetric_close_leaves_no_orphan_sentinels() -> None:
    """After both ends close, neither queue may hold a stray sentinel.

    Each ``close()`` used to enqueue a ``_CLOSE`` sentinel
    unconditionally. When both ends close, the second end's sentinel
    landed in a queue whose reader had already terminated — a slow leak
    of one sentinel per symmetric close. ``close()`` now checks
    ``peer_closed`` before the ``put``, so the second sentinel is
    skipped.
    """
    a, b = InMemoryConnection.paired()

    # Drain iter_lines on each end before symmetric close.
    a.close()
    list(b.iter_lines())
    b.close()

    # Inspect the inbound queues directly — both must be empty.
    a_inbound = a._endpoint[0]
    b_inbound = b._endpoint[0]
    assert a_inbound.qsize() == 0
    assert b_inbound.qsize() == 0


def test_iter_lines_blocks_until_peer_sends() -> None:
    a, b = InMemoryConnection.paired()
    received: list[dict[str, object]] = []

    def reader() -> None:
        received.extend(b.iter_lines())

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # Reader is blocked on the empty queue; verify by sending then closing.
    a.send_line({"op": "wake"})
    a.close()
    t.join(timeout=2.0)
    b.close()

    assert received == [{"op": "wake"}]
