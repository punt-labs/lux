"""LineSocket — round-trip JSON lines over a Unix-socket pair.

The wire transport is a module consumed by tests only. These tests
exercise its three end-to-end behaviors — duplex send/recv,
partial-chunk reassembly, and close propagation — against a
server/client pair joined by a real ``AF_UNIX`` socket.
"""

from __future__ import annotations

import logging
import socket
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.protocol.connection import (
    LineSocket,
    connect_unix,
    listen_unix,
    spawn_reader,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _accept_one(server_sock: socket.socket) -> LineSocket:
    """Block on ``accept`` and wrap the result as a LineSocket."""
    conn, _ = server_sock.accept()
    return LineSocket(conn)


@pytest.fixture
def short_socket_path() -> Iterator[Path]:
    """Yield a Unix-socket path short enough for the macOS ~104-char limit.

    ``tempfile.TemporaryDirectory(prefix="lux-ls-")`` lands the directory
    under ``$TMPDIR`` (typically ``/var/folders/.../T/``) so the resulting
    ``.../s.sock`` stays well under the ``AF_UNIX`` 104-char ceiling, and
    the context manager removes the directory on test exit — replacing the
    earlier ``tempfile.mkdtemp`` helper that leaked one directory per call.
    """
    with tempfile.TemporaryDirectory(prefix="lux-ls-") as d:
        yield Path(d) / "s.sock"


def test_send_recv_round_trip_carries_dicts_unchanged(
    short_socket_path: Path,
) -> None:
    sock_path = short_socket_path
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


def test_iter_lines_returns_when_peer_closes(
    short_socket_path: Path,
) -> None:
    sock_path = short_socket_path
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
    """Malformed input must log via ``logger.exception`` and let the
    reader thread exit cleanly instead of dying silently.

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


def test_spawn_reader_continues_after_handler_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SF10: a handler raising on every payload must be logged and survived.

    The inner ``try/except`` in ``spawn_reader``'s loop is the resilience
    contract — one misbehaving handler can't take down the reader thread.
    Send two valid JSON payloads through a real socketpair, fail every
    handler call, and assert (a) ``logger.exception`` records both
    failures with the "handler raised" marker, and (b) the thread terminates
    cleanly once the peer EOFs (so the inner branch did not bubble out).
    """
    raw_a, raw_b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader_socket = LineSocket(raw_b)
    call_count = [0]

    def always_raises(_payload: dict[str, object]) -> None:
        call_count[0] += 1
        msg = f"boom #{call_count[0]}"
        raise ValueError(msg)

    raw_a.sendall(b'{"op": "a"}\n{"op": "b"}\n')
    raw_a.shutdown(socket.SHUT_RDWR)
    raw_a.close()

    with caplog.at_level(logging.ERROR, logger="punt_lux.protocol.connection"):
        reader_thread = spawn_reader(reader_socket, always_raises)
        reader_thread.join(timeout=2.0)

    assert not reader_thread.is_alive(), "reader thread did not terminate"
    assert call_count[0] == 2, f"handler should fire per payload; got {call_count[0]}"
    handler_records = [
        r
        for r in caplog.records
        if r.name == "punt_lux.protocol.connection"
        and r.levelno == logging.ERROR
        and "handler raised" in r.message
        and r.exc_info is not None
    ]
    assert len(handler_records) == 2, (
        f"expected two logger.exception entries; got {caplog.records!r}"
    )


def test_spawn_reader_closes_line_socket_on_exit() -> None:
    """Ownership of the LineSocket transfers to the reader thread.

    When the peer EOFs and ``iter_lines`` returns, ``spawn_reader``'s
    ``finally`` must close the LineSocket so the underlying fd is released
    without the caller having to do it. Verified by ``send_line`` raising
    after the reader has terminated — a healthy socket would accept it.
    """
    raw_a, raw_b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader_socket = LineSocket(raw_b)
    handled: list[dict[str, object]] = []

    raw_a.shutdown(socket.SHUT_RDWR)
    raw_a.close()

    reader_thread = spawn_reader(reader_socket, handled.append)
    reader_thread.join(timeout=2.0)

    assert not reader_thread.is_alive(), "reader thread did not terminate"
    with pytest.raises(OSError):
        reader_socket.send_line({"op": "after-close"})


def test_spawn_reader_closes_line_socket_after_iter_lines_failure() -> None:
    """Close also runs when ``iter_lines`` raises, not just on EOF.

    Feeding malformed bytes drives ``iter_lines`` through ``JSONDecodeError``
    — the outer ``except Exception`` logs it, and the ``finally`` must
    still close the LineSocket so a failing reader doesn't leak the fd.
    """
    raw_a, raw_b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader_socket = LineSocket(raw_b)
    handled: list[dict[str, object]] = []

    raw_a.sendall(b"{not valid json}\n")
    raw_a.shutdown(socket.SHUT_RDWR)
    raw_a.close()

    reader_thread = spawn_reader(reader_socket, handled.append)
    reader_thread.join(timeout=2.0)

    assert not reader_thread.is_alive(), "reader thread did not terminate"
    with pytest.raises(OSError):
        reader_socket.send_line({"op": "after-failure"})


def test_connect_unix_closes_socket_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``connect_unix`` must release the fd on every non-success exit.

    Round-1 only handled the two retry-eligible races
    (``FileNotFoundError`` / ``ConnectionRefusedError``). Any other
    ``OSError`` — ``PermissionError`` being the canonical case —
    propagated without calling ``sock.close()``, leaking one fd per call.
    Patch ``socket.socket`` to return a tracked stub whose ``connect``
    raises ``PermissionError`` and assert (a) the error propagates,
    (b) the stub's ``close`` was invoked on the way out.
    """
    close_calls: list[int] = []

    class _StubSocket:
        """Minimal ``socket.socket`` stand-in: connect raises, close counts."""

        def __init__(self) -> None:
            self._id = len(close_calls) + 1

        def connect(self, _addr: str) -> None:
            msg = "permission denied"
            raise PermissionError(msg)

        def close(self) -> None:
            close_calls.append(self._id)

    def _stub_factory(_family: int, _type: int) -> _StubSocket:
        return _StubSocket()

    monkeypatch.setattr(socket, "socket", _stub_factory)

    with pytest.raises(PermissionError):
        connect_unix("/unused", retries=3, delay=0.0)

    assert close_calls == [1], (
        f"expected one close on the first failing attempt; got {close_calls!r}"
    )


def test_spawn_reader_dispatches_lines_to_handler(
    short_socket_path: Path,
) -> None:
    sock_path = short_socket_path
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

    assert handled == [{"op": "a"}, {"op": "b"}]
