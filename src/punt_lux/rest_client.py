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

from typing import TYPE_CHECKING, Self, final
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ValidationError

from punt_lux.hub_paths import HubPaths
from punt_lux.operations import (
    OpError,
    Pong,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
)
from punt_lux.rest_error_body import ErrorBody
from punt_lux.rest_loopback import LoopbackTransport
from punt_lux.rest_transport import HttpTransport, HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.operations.models.common import OpErrorCode

__all__ = ["LuxRestClient"]

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
        """Install a whole scene through ``PUT /scenes/{scene_id}``.

        The scene id is a path segment, so it is percent-encoded: a cwd-derived
        id bearing spaces or reserved characters must not break the request-target.
        """
        segment = quote(request.scene_id, safe="")
        return self._send(f"/scenes/{segment}", request, SceneShown)

    def render_table(self, request: RenderTableRequest) -> SceneShown | OpError:
        """Install a composed table scene through ``PUT /scenes/{scene_id}/table``.

        The Hub *constructs* the composition — search box, status combos, the
        grid, and a selection-bound detail panel wired through a shared
        ``FilteredTableModel`` — so its chrome runs Hub-side and stays live. A
        pre-composed tree pushed through ``render`` decodes to dead handlers; the
        table route carries the data and lets the Hub build the handlers.

        The scene id is a path segment, so it is percent-encoded, matching
        ``render``.
        """
        segment = quote(request.scene_id, safe="")
        return self._send(f"/scenes/{segment}/table", request, SceneShown)

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping through ``GET /display/ping``.

        A given ``wait`` rides through as the ``timeout`` query param (the
        display-leg budget); ``None`` omits it so luxd uses its standing budget.
        """
        suffix = f"?{urlencode({'timeout': wait})}" if wait is not None else ""
        return self._send(f"/display/ping{suffix}", None, Pong)

    def _send[T: BaseModel](
        self, path: str, body: BaseModel | None, ok: type[T]
    ) -> T | OpError:
        """Send ``body`` to ``path`` and read the reply as ``ok`` or an ``OpError``.

        The verb follows the body: this client writes scenes with a body (PUT)
        and reads the display ping without one (GET), so the caller never repeats
        a verb the body already implies.
        """
        method = "PUT" if body is not None else "GET"  # a body means a write (PUT)
        payload = body.model_dump_json().encode() if body is not None else None
        response = self._transport.request(method, path, payload)
        if 200 <= response.status < 300:
            try:
                return ok.model_validate_json(response.body)
            except ValidationError:
                # A 2xx whose body is not the model we expect is not success — a
                # stale ephemeral port answered by a foreign server makes this
                # real. Defend it like the error path, not with a traceback, and
                # name a short body preview so the wrong server is recognizable.
                snippet = ErrorBody(response.body).snippet()
                tail = f": {snippet}" if snippet else ""
                return OpError(
                    code="fault",
                    reason=f"luxd returned an unexpected {response.status} body{tail}",
                )
        return OpError(
            code=_CODE_BY_STATUS.get(response.status, "fault"),
            reason=ErrorBody(response.body).reason(response.status),
        )
