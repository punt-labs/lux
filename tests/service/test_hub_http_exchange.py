"""One HTTP deadline includes header and body I/O, not a new budget per read."""

from __future__ import annotations

import http.client
import socket
import threading
from unittest.mock import patch

import pytest

from punt_lux.service._hub_http_exchange import ReadinessHTTP


@pytest.mark.parametrize("close", [False, True])
def test_normal_connection_preserves_body_over_real_tcp(
    close: bool,
) -> None:
    payload = b"x" * 16384
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(2)

        def serve() -> None:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2)
                connection.recv(4096)
                header = b"Connection: close\r\n" if close else b""
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 16384\r\n"
                    + header
                    + b"\r\n"
                    + payload
                )

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with (
                patch(
                    "punt_lux.service._hub_http_exchange.HubPaths.read_port",
                    return_value=server.getsockname()[1],
                ),
                ReadinessHTTP(2).open() as connection,
            ):
                connection.request("GET", "/display")
                response = connection.getresponse()
                assert response.status == 200
                assert response.read(65536) == payload
        finally:
            thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("close", [False, True])
def test_slow_body_trickle_cannot_extend_the_absolute_deadline(close: bool) -> None:
    headers_read = threading.Event()
    expired = threading.Event()
    finished = threading.Event()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server,
        patch("punt_lux.service._readiness_http.time.monotonic") as clock,
        patch("punt_lux.service._readiness_http.threading.Timer") as timer,
    ):
        clock.return_value = 10
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(2)

        def serve() -> None:
            connection, _ = server.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n"
                    + (b"Connection: close\r\n" if close else b"")
                    + b"\r\nx"
                )
                if not headers_read.wait(2):
                    return
                connection.sendall(b"xx")
                clock.return_value = 12
                callback = timer.call_args.args[1]
                callback(*timer.call_args.kwargs["args"])
                expired.set()
                finished.wait(2)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with (
                patch(
                    "punt_lux.service._hub_http_exchange.HubPaths.read_port",
                    return_value=server.getsockname()[1],
                ),
                pytest.raises(http.client.HTTPException),
                ReadinessHTTP(1).open() as connection,
            ):
                connection.request("GET", "/display")
                response = connection.getresponse()
                headers_read.set()
                response.read()
        finally:
            finished.set()
            thread.join(timeout=2)
        assert not thread.is_alive()
        assert timer.call_args.args[0] == 1
        assert expired.is_set()
        timer.return_value.start.assert_called_once()
        timer.return_value.cancel.assert_called_once()


@pytest.mark.parametrize("close", [False, True])
@pytest.mark.slow
def test_real_watchdog_interrupts_a_trickling_body_without_thread_errors(
    monkeypatch: pytest.MonkeyPatch, close: bool
) -> None:
    errors: list[threading.ExceptHookArgs] = []
    monkeypatch.setattr(threading, "excepthook", errors.append)
    stopped = threading.Event()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)

        def serve() -> None:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                connection.recv(4096)
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n"
                    + (b"Connection: close\r\n" if close else b"")
                    + b"\r\n"
                )
                for _ in range(1000):
                    if stopped.wait(0.01):
                        break
                    try:
                        connection.sendall(b"x")
                    except OSError:
                        break

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with (
                patch(
                    "punt_lux.service._hub_http_exchange.HubPaths.read_port",
                    return_value=server.getsockname()[1],
                ),
                pytest.raises(
                    (http.client.IncompleteRead, ConnectionResetError)
                ) as interrupted,
                ReadinessHTTP(2).open() as connection,
            ):
                connection.request("GET", "/display")
                connection.getresponse().read()
            if isinstance(interrupted.value, http.client.IncompleteRead):
                assert 0 < len(interrupted.value.partial) < 1000
        finally:
            stopped.set()
            thread.join(timeout=5)
        assert not thread.is_alive()
        assert not errors
