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

import json
from typing import TYPE_CHECKING, Self, cast, final
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ValidationError

from punt_lux.hub_paths import HubPaths
from punt_lux.operations import OpError, Pong, RenderRequest, SceneShown
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

# A malformed-2xx fault names a short body preview so a stale/foreign server on
# the old port is recognizable; bounded so a binary or huge body stays safe.
_SNIPPET_LIMIT = 120


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
        return self._send("PUT", f"/scenes/{segment}", request, SceneShown)

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping through ``GET /display/ping``.

        A given ``wait`` rides through as the ``timeout`` query param (the
        display-leg budget); ``None`` omits it so luxd uses its standing budget.
        """
        suffix = f"?{urlencode({'timeout': wait})}" if wait is not None else ""
        return self._send("GET", f"/display/ping{suffix}", None, Pong)

    def _send[T: BaseModel](
        self, method: str, path: str, body: BaseModel | None, ok: type[T]
    ) -> T | OpError:
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
                snippet = self._body_snippet(response.body)
                tail = f": {snippet}" if snippet else ""
                return OpError(
                    code="fault",
                    reason=f"luxd returned an unexpected {response.status} body{tail}",
                )
        return OpError(
            code=_CODE_BY_STATUS.get(response.status, "fault"),
            reason=self._detail_of(response.status, response.body),
        )

    @staticmethod
    def _body_snippet(body: bytes) -> str:
        """A one-line, printable, bounded preview of a raw body.

        The ``errors="replace"`` decode never raises on binary bytes, non-printable
        characters collapse to spaces, whitespace runs fold to one, and the result
        is truncated so a huge body cannot bloat the reason.
        """
        text = body.decode(errors="replace")
        printable = "".join(c if c.isprintable() else " " for c in text)
        oneline = " ".join(printable.split())
        if len(oneline) <= _SNIPPET_LIMIT:
            return oneline
        return oneline[:_SNIPPET_LIMIT] + "…"

    @staticmethod
    def _detail_of(status: int, body: bytes) -> str:
        """Render an error body's human reason, never blank or ``None``.

        An empty body falls back to the status line; a blank reason (empty
        detail string, empty detail list) falls back to the decoded body. Since
        the decoded body is non-blank here, the message always carries content.
        """
        text = body.decode(errors="replace")
        if not text.strip():
            return f"HTTP {status}"
        reason = LuxRestClient._reason_in(text)
        return reason if reason.strip() else text

    @staticmethod
    def _reason_in(text: str) -> str:
        """Pull the human reason from a JSON error body, or the body itself.

        ``text`` is the already-decoded body (``errors="replace"``), so parsing
        it never raises on non-UTF-8 bytes (decoding those raw would escape as an
        unhandled ``UnicodeDecodeError``). It is a JSON wire value narrowed here
        (PY-TS-14): a semantic ``OpError`` sends a bare ``detail`` string; a
        FastAPI binding rejection sends ``{loc, msg, type}`` items whose ``msg``
        fields are joined. Anything else yields the text so its content survives.
        """
        try:
            parsed: object = json.loads(text)
        except json.JSONDecodeError:
            return text
        if not isinstance(parsed, dict):
            return text
        detail: object = cast("dict[str, object]", parsed).get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            items = cast("list[object]", detail)
            return "; ".join(map(LuxRestClient._item_message, items))
        return text

    @staticmethod
    def _item_message(item: object) -> str:
        """Render one located-error item as its ``msg``, or itself if not a dict."""
        if not isinstance(item, dict):
            return str(item)
        fields = cast("dict[str, object]", item)
        msg = fields.get("msg")
        return str(msg) if msg is not None else str(fields)
