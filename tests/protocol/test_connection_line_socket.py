"""LineSocket — round-trip JSON lines over a Unix-socket pair.

Per docs/oo-refactor/pr3-v2.1-design.md §7(iv): commit (iv) lands the
io-model transport as a new module consumed by tests only (D7). These
tests exercise the three behaviors the spike validated end-to-end —
duplex send/recv, partial-chunk reassembly, and close propagation —
against a server/client pair joined by a real ``AF_UNIX`` socket.
"""

from __future__ import annotations

import logging
import socket
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from punt_lux.protocol.connection import (
    LineSocket,
    connect_unix,
    listen_unix,
    spawn_reader,
)

if TYPE_CHECKING:
    import pytest


def _accept_one(server_sock: socket.socket) -> LineSocket:
    """Block on ``accept`` and wrap the result as a LineSocket."""
    conn, _ = server_sock.accept()
    return LineSocket(conn)


def _short_socket_path() -> Path:
    """Return a Unix-socket path short enough for the macOS ~104-char limit."""
    return Path(tempfile.mkdtemp(prefix="lux-ls-")) / "s.sock"


def test_send_recv_round_trip_carries_dicts_unchanged() -> None:
    sock_path = _short_socket_path()
    accepted: list[LineSocket] = []

    with listen_unix(sock_path) as server_sock:
        accept_thread = threading.Thread(
            target=lambda: accepted.append(_accept_one(server_sock)),
            daemon=True,
        )
        accept_thread.start()
        client = connect_unix(sock_path, retries=20, delay=0.01)
        accept_thread.join(timeout=2.0)
        server = accepted[0]

        client.send_line({"op": "ping", "id": 1})
        client.send_line({"op": "ping", "id": 2})
        client.close()

        received = list(server.iter_lines())
        server.close()

    assert received == [{"op": "ping", "id": 1}, {"op": "ping", "id": 2}]


def test_iter_lines_reassembles_partial_chunks() -> None:
    # Use a raw socketpair so we can feed bytes one chunk at a time without
    # reaching into LineSocket internals. iter_lines must buffer until the
    # terminating newline arrives before yielding.
    raw_a, raw_b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader = LineSocket(raw_b)

    raw_a.sendall(b'{"op": "split",')
    raw_a.sendall(b' "n": 7}\n{"op":')
    raw_a.sendall(b' "second", "n": 8}\n')
    raw_a.shutdown(socket.SHUT_RDWR)
    raw_a.close()

    received = list(reader.iter_lines())
    reader.close()

    assert received == [
        {"op": "split", "n": 7},
        {"op": "second", "n": 8},
    ]


def test_iter_lines_returns_when_peer_closes() -> None:
    sock_path = _short_socket_path()
    accepted: list[LineSocket] = []

    with listen_unix(sock_path) as server_sock:
        accept_thread = threading.Thread(
            target=lambda: accepted.append(_accept_one(server_sock)),
            daemon=True,
        )
        accept_thread.start()
        client = connect_unix(sock_path, retries=20, delay=0.01)
        accept_thread.join(timeout=2.0)
        server = accepted[0]

        # Close the client without sending any data; the server's iterator
        # must terminate on the EOF rather than block forever.
        client.close()

        received = list(server.iter_lines())
        server.close()

    assert received == []


def test_spawn_reader_logs_and_terminates_on_malformed_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SF1 regression: malformed input must log via ``logger.exception`` and
    let the reader thread exit cleanly instead of dying silently.

    Before the fix at 8c6fb02 the unprotected ``for payload in
    iter_lines():`` loop swallowed ``JSONDecodeError`` (and ``OSError``,
    ``ConnectionResetError``, ``UnicodeDecodeError``) — the daemon
    thread terminated with no log entry and the hub went deaf. The
    outer ``try/except`` in ``spawn_reader`` must surface those failures
    and finish the loop.
    """
    raw_a, raw_b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader_socket = LineSocket(raw_b)
    handled: list[dict[str, object]] = []

    raw_a.sendall(b"{not valid json}\n")
    raw_a.shutdown(socket.SHUT_RDWR)
    raw_a.close()

    with caplog.at_level(logging.ERROR, logger="punt_lux.protocol.connection"):
        reader_thread = spawn_reader(reader_socket, handled.append)
        reader_thread.join(timeout=2.0)

    reader_socket.close()

    assert not reader_thread.is_alive(), "reader thread did not terminate"
    assert handled == [], "handler must not see lines after a decode failure"
    matching = [
        r
        for r in caplog.records
        if r.name == "punt_lux.protocol.connection"
        and r.levelno == logging.ERROR
        and r.exc_info is not None
    ]
    assert matching, (
        f"expected logger.exception on iter_lines failure; got {caplog.records!r}"
    )
    assert "iter_lines terminated unexpectedly" in matching[0].message


def test_spawn_reader_dispatches_lines_to_handler() -> None:
    sock_path = _short_socket_path()
    accepted: list[LineSocket] = []
    handled: list[dict[str, object]] = []
    done = threading.Event()

    def handler(payload: dict[str, object]) -> None:
        handled.append(payload)
        if len(handled) == 2:
            done.set()

    with listen_unix(sock_path) as server_sock:
        accept_thread = threading.Thread(
            target=lambda: accepted.append(_accept_one(server_sock)),
            daemon=True,
        )
        accept_thread.start()
        client = connect_unix(sock_path, retries=20, delay=0.01)
        accept_thread.join(timeout=2.0)
        server = accepted[0]

        reader = spawn_reader(server, handler)
        client.send_line({"op": "a"})
        client.send_line({"op": "b"})
        assert done.wait(timeout=2.0), f"reader handled {handled!r}, expected 2"
        client.close()
        reader.join(timeout=2.0)
        server.close()

    assert handled == [{"op": "a"}, {"op": "b"}]
