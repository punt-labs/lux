"""The CLI's REST client — over a fake transport and the real REST surface.

The parsing and error-mapping tests drive a canned transport so every branch is
exact and offline. The end-to-end tests wire the client through a TestClient
transport onto the real ``RestSurface`` over fake collaborators, proving the
client and the routes agree on the wire — the same fake-ports harness the REST
route tests use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.cli_identity import CliIdentity
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.hub_paths import HubPaths
from punt_lux.operations import (
    OpError,
    Pong,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
)
from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_transport import HttpResponse, HubUnavailableError

from .rest._fakes import make_client

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from punt_lux.rest_http_call import HttpCall

_TEXT: dict[str, object] = {"kind": "text", "id": "t1", "content": "hi"}
_IDENTITY = ClientIdentity(kind="cli", name="rest-test", repo="/w/lux")


class CannedTransport:
    """Return one preset reply, or raise, recording the last call it was handed."""

    def __init__(self, reply: HttpResponse | HubUnavailableError) -> None:
        self._reply = reply
        self.call: HttpCall | None = None

    def request(self, call: HttpCall) -> HttpResponse:
        self.call = call
        if isinstance(self._reply, HubUnavailableError):
            raise self._reply
        return self._reply


class SurfaceTransport:
    """Route the client's calls into a FastAPI ``TestClient``.

    Mirrors ``LoopbackTransport``: the call's ``wire_headers`` carry the caller's
    identity and a JSON content-type for a body, so FastAPI binds the body as a
    request model rather than a bare string.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def request(self, call: HttpCall) -> HttpResponse:
        resp = self._client.request(
            call.method, call.path, content=call.body, headers=call.wire_headers()
        )
        return HttpResponse(status=resp.status_code, body=resp.content)


def _client_over(transport: object) -> LuxRestClient:
    return LuxRestClient(transport, _IDENTITY)  # type: ignore[arg-type]  # HttpTransport protocol; fakes satisfy it structurally


def _sent(transport: CannedTransport) -> HttpCall:
    """Return the call the transport recorded, asserting one was made."""
    assert transport.call is not None
    return transport.call


def _render_request(scene_id: str = "s1") -> RenderRequest:
    return RenderRequest(scene_id=scene_id, elements=[_TEXT])


# --- parsing and error mapping over a canned transport -----------------------


def test_render_returns_the_typed_success() -> None:
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","scene_id":"s1"}')
    )
    result = _client_over(transport).render(_render_request())
    assert result == SceneShown(scene_id="s1")
    call = _sent(transport)
    assert call.method == "PUT"
    assert call.path == "/scenes/s1"
    assert call.body is not None


def test_render_table_targets_the_table_route() -> None:
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","scene_id":"issues"}')
    )
    request = RenderTableRequest(
        scene_id="issues",
        columns=["ID", "Title"],
        rows=[["i1", "one"]],
    )
    result = _client_over(transport).render_table(request)
    assert result == SceneShown(scene_id="issues")
    call = _sent(transport)
    assert call.method == "PUT"
    assert call.path == "/scenes/issues/table"
    assert call.body is not None


def test_identity_headers_ride_a_write() -> None:
    # Every request carries the caller's identity so the Hub attributes the write.
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","scene_id":"s1"}')
    )
    _client_over(transport).render(_render_request())
    headers = _sent(transport).wire_headers()
    assert headers["X-Lux-Client-Kind"] == "cli"
    assert headers["X-Lux-Client-Name"] == "rest-test"
    assert headers["X-Lux-Client-Repo"] == "/w/lux"


def test_identity_headers_ride_a_bodiless_read() -> None:
    # A GET carries the identity too — headers ride regardless of a body.
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","rtt_seconds":0.01}')
    )
    _client_over(transport).ping(1.0)
    assert _sent(transport).wire_headers()["X-Lux-Client-Name"] == "rest-test"


def test_ping_returns_the_typed_pong() -> None:
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","rtt_seconds":0.01}')
    )
    result = _client_over(transport).ping(2.5)
    assert result == Pong(rtt_seconds=0.01)
    call = _sent(transport)
    assert call.method == "GET"
    assert call.body is None
    # The display-leg budget rides through as the timeout query param.
    assert call.path == "/display/ping?timeout=2.5"


def test_ping_without_a_wait_omits_the_timeout_param() -> None:
    # No wait -> no query param, so the route falls to luxd's standing budget.
    transport = CannedTransport(
        HttpResponse(status=200, body=b'{"kind":"ok","rtt_seconds":0.02}')
    )
    result = _client_over(transport).ping(None)
    assert result == Pong(rtt_seconds=0.02)
    assert _sent(transport).path == "/display/ping"


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


def test_a_non_utf8_error_body_maps_cleanly_without_raising() -> None:
    # Raw non-UTF-8 bytes must not escape the error path as a UnicodeDecodeError.
    # The reason parses the errors="replace" decode, so a bad-bytes body maps to
    # a fault whose reason survives (replacement chars), never a traceback.
    transport = CannedTransport(HttpResponse(status=502, body=b"\xff\xfe boom"))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert result.reason == b"\xff\xfe boom".decode(errors="replace")


def test_an_empty_error_body_falls_back_to_the_status_line() -> None:
    transport = CannedTransport(HttpResponse(status=503, body=b""))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"
    assert result.reason == "HTTP 503"


@pytest.mark.parametrize("body", [b'{"detail":""}', b'{"detail":[]}'])
def test_a_blank_detail_falls_back_to_the_body(body: bytes) -> None:
    # An empty detail string or empty detail list must not leave the reason
    # blank ("Beads board not shown:"); the decoded body is the fallback so the
    # message always carries content.
    transport = CannedTransport(HttpResponse(status=502, body=body))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.reason.strip()
    assert result.reason == body.decode()


def test_a_malformed_2xx_body_is_a_fault_naming_a_body_snippet() -> None:
    # A 200 whose body is not the expected model — a stale ephemeral port
    # answered by a foreign server — must not raise past the client. It becomes
    # a fault whose reason names a short body preview so the wrong server on the
    # old port is recognizable rather than guessed at.
    transport = CannedTransport(HttpResponse(status=200, body=b'{"wrong":"shape"}'))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert "unexpected" in result.reason
    assert '{"wrong":"shape"}' in result.reason  # the snippet appears


def test_a_malformed_2xx_reason_truncates_a_huge_body() -> None:
    # The preview is bounded so a huge (or binary) body cannot bloat the reason:
    # it stays a single truncated line, not the whole payload.
    body = b'{"junk":"' + b"A" * 5000 + b'"}'
    transport = CannedTransport(HttpResponse(status=200, body=body))
    result = _client_over(transport).render(_render_request())
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert "AAAA" in result.reason  # a recognizable slice of the body survives
    assert "…" in result.reason  # ... but it is truncated with a marker
    assert len(result.reason) < 200  # bounded, not the full 5 KB


def test_transport_failure_propagates_as_hub_unavailable() -> None:
    transport = CannedTransport(HubUnavailableError("luxd is not reachable"))
    with pytest.raises(HubUnavailableError, match="not reachable"):
        _client_over(transport).ping(5.0)


# --- end to end against the real REST surface --------------------------------


def test_render_installs_a_scene_over_the_real_surface() -> None:
    client = _client_over(SurfaceTransport(make_client()))
    result = client.render(_render_request("alpha"))
    assert result == SceneShown(scene_id="alpha")


def test_a_derived_cli_identity_owns_its_scene_by_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The operator's probe, closed end to end: a cli invocation derives its
    # identity from the git root and the scene it installs is owned by that repo —
    # never the old anonymous "rest".
    repo = tmp_path / "myrepo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("LUX_CLIENT", raising=False)

    surface = make_client()
    client = LuxRestClient(SurfaceTransport(surface), CliIdentity.resolve())
    assert client.render(_render_request("board")) == SceneShown(scene_id="board")

    scene = next(
        s for s in surface.get("/scenes").json()["scenes"] if s["scene_id"] == "board"
    )
    identity = scene["owners"][0]["identity"]
    assert identity["kind"] == "cli"
    assert identity["name"] == "myrepo"
    assert identity["repo"] == str(repo)


def test_render_table_composes_a_live_scene_over_the_real_surface() -> None:
    # The table route carries data; the Hub *constructs* the composition. The
    # scene the surface installs holds the composed chrome (a group with the
    # grid, search box, and combos), not the bare data — proof the route builds
    # handlers rather than decoding a dead tree.
    client = _client_over(SurfaceTransport(make_client()))
    request = RenderTableRequest(
        scene_id="issues",
        columns=["ID", "Title", "Status"],
        rows=[["i1", "one", "open"], ["i2", "two", "closed"]],
        filters=[
            {"type": "search", "column": [0, 1], "hint": "Filter..."},
            {"type": "combo", "column": 2, "label": "Status", "items": ["All", "open"]},
        ],
    )
    result = client.render_table(request)
    assert result == SceneShown(scene_id="issues")


def test_render_round_trips_a_space_bearing_scene_id() -> None:
    # A cwd-derived scene id can carry spaces or reserved characters; the client
    # percent-encodes the path segment and the real surface decodes it back, so
    # the id survives the request-target intact.
    client = _client_over(SurfaceTransport(make_client()))
    result = client.render(_render_request("beads-my project"))
    assert result == SceneShown(scene_id="beads-my project")


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
