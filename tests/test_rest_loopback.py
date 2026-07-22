"""The production loopback transport — over real sockets, no luxd process.

A refused connection must surface as ``HubUnavailableError`` rather than a raw
``OSError``; a reachable server's reply must come back as an ``HttpResponse``
with the body read and the connection closed.
"""

from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

import pytest

from punt_lux.rest_loopback import LoopbackTransport
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def _bound_unlistened_port() -> Generator[int]:
    """Bind :0 without listening and hold it for the caller's scope.

    A bound socket that never calls ``listen`` has no accept queue, so the
    kernel refuses inbound connections with ECONNREFUSED. Holding it open keeps
    the port from being reused mid-test, which is what makes the refusal
    deterministic — releasing it (the old shape) freed the port to be reassigned
    and answered by something else.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        yield int(probe.getsockname()[1])
    finally:
        probe.close()


def test_loopback_transport_wraps_a_refused_connection() -> None:
    # A bound-but-unlistened port refuses the connection; the transport reports
    # luxd unreachable rather than leaking the OSError.
    with _bound_unlistened_port() as port:
        transport = LoopbackTransport(port, timeout=1.0)
        with pytest.raises(HubUnavailableError, match="not reachable"):
            transport.request("GET", "/display/ping", None)


def test_loopback_transport_sends_json_and_reads_the_reply() -> None:
    captured: dict[str, object] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_PUT(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            captured["path"] = self.path
            captured["content_type"] = self.headers.get("Content-Type")
            captured["body"] = self.rfile.read(length)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"kind":"ok","scene_id":"s1"}')

        def log_message(self, format: str, *args: object) -> None:
            """Silence the default stderr access log."""

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    worker = threading.Thread(target=server.handle_request)
    worker.start()
    try:
        transport = LoopbackTransport(server.server_address[1], timeout=2.0)
        response = transport.request("PUT", "/scenes/s1", b'{"scene_id":"s1"}')
    finally:
        worker.join(timeout=2.0)
        server.server_close()
    # The reply was read back, and the connection carried a JSON content-type and
    # the exact path. The request returned (the finally-close ran) without leak.
    assert response.status == 200
    assert response.body == b'{"kind":"ok","scene_id":"s1"}'
    assert captured["path"] == "/scenes/s1"
    assert captured["content_type"] == "application/json"
    assert captured["body"] == b'{"scene_id":"s1"}'
