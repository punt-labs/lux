"""The command-line tool's HTTP client of luxd's REST surface.

The CLI is the third thin client of the one engine. An MCP agent reaches the Hub
through a tool and a REST caller through a route; ``lux show beads`` and
``lux ping`` reach it through :class:`LuxRestClient`. The client locates luxd's
port, speaks the operations layer's request and result models over HTTP, and
never touches the display socket — the Hub decides whether the display is
reachable and answers with a typed result.

Two failures are distinct. luxd being unreachable — no port file, a refused
connection, a stalled response — is the one exceptional outcome and raises
:class:`HubUnavailableError` with an actionable message. The Hub's own refusal of
a reachable request comes back as a typed :class:`OpError` in the result, mapped
from the HTTP status the shared REST error table produced.
"""

from __future__ import annotations

import http.client
import json
from typing import TYPE_CHECKING, Self, cast, final

from pydantic import BaseModel

from punt_lux.hub_paths import HubPaths
from punt_lux.operations import OpError, Pong, RenderRequest, SceneShown
from punt_lux.rest_transport import HttpResponse, HttpTransport, HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.operations.models.common import OpErrorCode

__all__ = ["LoopbackTransport", "LuxRestClient"]

# The inverse of the REST error table (rest/status.py maps code -> status): the
# client observes the same wire contract from the other end. The statuses are
# distinct, so the inverse is total; an unexpected status is an engine fault.
_CODE_BY_STATUS: dict[int, OpErrorCode] = {
    422: "invalid_request",
    404: "not_found",
    409: "rejected",
    502: "fault",
    503: "display_unavailable",
    504: "timeout",
}


@final
class LoopbackTransport:
    """The production transport: one loopback HTTP round-trip with one timeout.

    A non-2xx reply from a reachable luxd is a result, not a failure — the status
    and body come back as an :class:`HttpResponse`; only an unreachable or stalled
    luxd raises :class:`HubUnavailableError`. There is no retry — the budget for a
    loopback call is milliseconds, and a stall means luxd is down, not busy.
    """

    _port: int
    _timeout: float
    __slots__ = ("_port", "_timeout")

    def __new__(cls, port: int, timeout: float) -> Self:
        self = super().__new__(cls)
        self._port = port
        self._timeout = timeout
        return self

    def request(self, method: str, path: str, body: bytes | None) -> HttpResponse:
        conn = http.client.HTTPConnection(
            "127.0.0.1", self._port, timeout=self._timeout
        )
        headers = {"Content-Type": "application/json"} if body is not None else {}
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return HttpResponse(status=response.status, body=response.read())
        except (OSError, http.client.HTTPException) as exc:
            raise HubUnavailableError(
                f"luxd is not reachable on port {self._port} — {exc}"
            ) from exc
        finally:
            conn.close()


@final
class LuxRestClient:
    """A thin typed client of luxd's REST routes, owned by the CLI layer."""

    _transport: HttpTransport
    __slots__ = ("_transport",)

    def __new__(cls, transport: HttpTransport) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        return self

    @classmethod
    def connect(cls, *, timeout: float = 2.0) -> Self:
        """Locate luxd's port and build a client, or raise if luxd is not running."""
        port = HubPaths().read_port()
        if port is None:
            raise HubUnavailableError(
                "luxd is not running. Run 'lux hub-install' to register the service."
            )
        return cls(LoopbackTransport(port, timeout))

    def render(self, request: RenderRequest) -> SceneShown | OpError:
        """Install a whole scene through ``PUT /scenes/{scene_id}``."""
        return self._send("PUT", f"/scenes/{request.scene_id}", request, SceneShown)

    def ping(self) -> Pong | OpError:
        """Round-trip a display ping through ``GET /display/ping``."""
        return self._send("GET", "/display/ping", None, Pong)

    def _send[T: BaseModel](
        self, method: str, path: str, body: BaseModel | None, ok: type[T]
    ) -> T | OpError:
        payload = body.model_dump_json().encode() if body is not None else None
        response = self._transport.request(method, path, payload)
        if 200 <= response.status < 300:
            return ok.model_validate_json(response.body)
        return OpError(
            code=_CODE_BY_STATUS.get(response.status, "fault"),
            reason=self._detail_of(response.body),
        )

    @staticmethod
    def _detail_of(body: bytes) -> str:
        """Read FastAPI's ``detail`` from an error body, string or located-list.

        The body is a JSON wire value, so it decodes to ``object`` and is
        narrowed here (PY-TS-14 wire boundary): a semantic ``OpError`` sends a
        bare ``detail`` string; FastAPI's own binding rejection sends a list of
        ``{loc, msg, type}`` items whose ``msg`` fields are joined.
        """
        try:
            parsed: object = json.loads(body)
        except json.JSONDecodeError:
            return body.decode(errors="replace")
        if not isinstance(parsed, dict):
            return str(parsed)
        detail: object = cast("dict[str, object]", parsed).get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            items = cast("list[object]", detail)
            return "; ".join(LuxRestClient._item_message(item) for item in items)
        return str(detail)

    @staticmethod
    def _item_message(item: object) -> str:
        """Render one located-error item as its ``msg``, or itself if not a dict."""
        if not isinstance(item, dict):
            return str(item)
        fields = cast("dict[str, object]", item)
        msg = fields.get("msg")
        return str(msg) if msg is not None else str(fields)
