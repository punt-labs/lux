"""InMemoryConnection — paired-queue duplex for in-process tests.

Per docs/oo-refactor/pr3-v2.1-design.md §5: the in-memory backend lets
PR 3+ tests drive both ends of an io-model duplex without crossing a
real socket. ``paired()`` returns the two ends already wired so a
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
