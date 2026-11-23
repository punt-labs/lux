"""One HTTP deadline includes header and body I/O, not a new budget per read."""

from __future__ import annotations

import socket
import threading
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service._readiness_http import ReadinessHTTP


@pytest.mark.parametrize("close", [False, True])
def test_connection_uses_the_budgeted_response_factory_over_real_tcp(
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
                    "punt_lux.service._readiness_http.HubPaths.read_port",
                    return_value=server.getsockname()[1],
                ),
                ReadinessHTTP.open(2) as connection,
            ):
                connection.request("GET", "/display")
                response = connection.getresponse()
                assert response.status == 200
                assert response.read(65536) == payload
        finally:
            thread.join(timeout=2)
        assert not thread.is_alive()


def test_response_adapter_parses_real_headers_and_body() -> None:
    left, right = socket.socketpair()
    with left, right:
        right.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        with patch("punt_lux.service._readiness_http.time.monotonic", return_value=0):
            response = ReadinessHTTP._response(left, deadline=1)
            response.begin()
            assert response.status == 200
            assert response.read(65536) == b"{}"
            response.close()


def test_a_later_read_gets_only_the_remaining_budget_and_expiry_starts_no_io() -> None:
    sock = MagicMock()
    reader = ReadinessHTTP(sock, 1)
    owned = sock.dup.return_value
    owned.recv_into.return_value = 1
    with patch("punt_lux.service._readiness_http.time.monotonic") as clock:
        clock.return_value = 0.9
        assert reader.readinto(bytearray(1)) == 1
        assert owned.settimeout.call_args.args[0] == pytest.approx(0.1)
        clock.return_value = 1
        with pytest.raises(TimeoutError):
            reader.readinto(bytearray(1))
    owned.recv_into.assert_called_once()
    reader.close()
    owned.close.assert_called_once()
