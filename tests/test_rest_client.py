"""The CLI's REST client — over a fake transport and the real REST surface.

The parsing and error-mapping tests drive a canned transport so every branch is
exact and offline. The end-to-end tests wire the client through a TestClient
transport onto the real ``RestSurface`` over fake collaborators, proving the
client and the routes agree on the wire — the same fake-ports harness the REST
route tests use.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

import pytest

from punt_lux.hub_paths import HubPaths
from punt_lux.operations import OpError, Pong, RenderRequest, SceneShown
from punt_lux.rest_client import LoopbackTransport, LuxRestClient
from punt_lux.rest_transport import HttpResponse, HubUnavailableError

from .rest._fakes import make_client

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

_TEXT: dict[str, object] = {"kind": "text", "id": "t1", "content": "hi"}


class CannedTransport:
    """Return one preset reply, or raise, recording the last request."""

    def __init__(self, reply: HttpResponse | HubUnavailableError) -> None:
        self._reply = reply
        self.method = ""
        self.path = ""
        self.body: bytes | None = None

    def request(self, method: str, path: str, body: bytes | None) -> HttpResponse:
        self.method, self.path, self.body = method, path, body
        if isinstance(self._reply, HubUnavailableError):
            raise self._reply
        return self._reply


class SurfaceTransport:
    """Route the client's requests into a FastAPI ``TestClient``.

    Mirrors ``LoopbackTransport``: a JSON content-type accompanies any body, so
    FastAPI binds it as a request model rather than a bare string.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def request(self, method: str, path: str, body: bytes | None) -> HttpResponse:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        resp = self._client.request(method, path, content=body, headers=headers)
        return HttpResponse(status=resp.status_code, body=resp.content)


def _client_over(transport: object) -> LuxRestClient:
    return LuxRestClient(transport)  # type: ignore[arg-type]  # HttpTransport protocol; fakes satisfy it structurally


def _render_request(scene_id: str = "s1") -> RenderRequest:
    return RenderRequest(scene_id=scene_id, elements=[_TEXT])


# --- parsing and error mapping over a canned transport -----------------------


def test_render_returns_the_typed_success() -> None:
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","scene_id":"s1"}')
    )
    result = _client_over(transport).render(_render_request())
    assert result == SceneShown(scene_id="s1")
    assert transport.method == "PUT"
    assert transport.path == "/scenes/s1"
    assert transport.body is not None


def test_ping_returns_the_typed_pong() -> None:
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","rtt_seconds":0.01}')
    )
    result = _client_over(transport).ping()
    assert result == Pong(rtt_seconds=0.01)
    assert transport.method == "GET"
    assert transport.body is None


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (422, "invalid_request"),
        (404, "not_found"),
        (409, "rejected"),
        (502, "fault"),
        (503, "display_unavailable"),
        (504, "timeout"),
    ],
)
def test_error_status_maps_to_the_op_error_code(status: int, code: str) -> None:
    transport = CannedTransport(HttpResponse(status=status, body=b'{"detail":"nope"}'))
    result = _client_over(transport).render(_render_request())
    assert result == OpError(code=code, reason="nope")  # type: ignore[arg-type]  # code is a parametrized OpErrorCode literal


def test_an_unexpected_status_is_a_fault() -> None:
    transport = CannedTransport(HttpResponse(status=500, body=b"boom"))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert result.reason == "boom"


def test_a_located_list_detail_is_flattened() -> None:
    # FastAPI's own body-binding rejection carries a list of {loc, msg, type}.
    body = b'{"detail":[{"loc":["body","layout"],"msg":"bad value","type":"x"}]}'
    transport = CannedTransport(HttpResponse(status=422, body=body))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.reason == "bad value"


def test_a_dict_error_body_without_detail_preserves_its_content() -> None:
    # No FastAPI "detail" key — a foreign JSON error object. The reason must keep
    # the body's content, not collapse to the string "None".
    transport = CannedTransport(HttpResponse(status=502, body=b'{"error":"boom"}'))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.reason == '{"error":"boom"}'


def test_an_empty_error_body_falls_back_to_the_status_line() -> None:
    transport = CannedTransport(HttpResponse(status=503, body=b""))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"
    assert result.reason == "HTTP 503"


def test_a_malformed_2xx_body_is_a_fault_not_a_traceback() -> None:
    # A 200 whose body is not the expected model — a stale ephemeral port
    # answered by a foreign server — must not raise past the client. It becomes
    # a fault, defended the same way the error path is.
    transport = CannedTransport(HttpResponse(status=200, body=b'{"wrong":"shape"}'))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert "unexpected" in result.reason


def test_transport_failure_propagates_as_hub_unavailable() -> None:
    transport = CannedTransport(HubUnavailableError("luxd is not reachable"))
    with pytest.raises(HubUnavailableError, match="not reachable"):
        _client_over(transport).ping()


# --- end to end against the real REST surface --------------------------------


def test_render_installs_a_scene_over_the_real_surface() -> None:
    client = _client_over(SurfaceTransport(make_client()))
    result = client.render(_render_request("alpha"))
    assert result == SceneShown(scene_id="alpha")


def test_render_reports_a_duplicate_id_as_a_rejected_error() -> None:
    dup: list[dict[str, object]] = [
        {"kind": "text", "id": "d", "content": "a"},
        {"kind": "text", "id": "d", "content": "b"},
    ]
    client = _client_over(SurfaceTransport(make_client()))
    result = client.render(RenderRequest(scene_id="s1", elements=dup))
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert "duplicate" in result.reason


def test_connect_raises_the_actionable_message_when_no_port_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_port(_self: HubPaths) -> int | None:
        return None

    monkeypatch.setattr(HubPaths, "read_port", _no_port)
    with pytest.raises(HubUnavailableError) as excinfo:
        LuxRestClient.connect()
    # Pin the production string end to end, hint included — the CLI prints this
    # verbatim, so the actionable "run lux hub-install" guidance must be here.
    message = str(excinfo.value)
    assert message == (
        "luxd is not running. Run 'lux hub-install' to register the service."
    )


# --- the production loopback transport ---------------------------------------


def _unused_loopback_port() -> int:
    """Bind :0, read the assigned port, release it — likely still free."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    return port


def test_loopback_transport_wraps_a_refused_connection() -> None:
    # A closed port refuses the connection; the transport reports luxd
    # unreachable rather than leaking the OSError.
    transport = LoopbackTransport(_unused_loopback_port(), timeout=1.0)
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
