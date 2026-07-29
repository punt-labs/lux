"""The command-line tool's HTTP client of luxd's REST surface.

The CLI is the third thin client of the one engine. An MCP agent reaches the Hub
through a tool and a REST caller through a route; ``lux show beads`` and
``lux ping`` reach it through :class:`LuxRestClient`. The client locates luxd's
port, speaks the operations layer's request and result models over HTTP, and
never touches the display socket — the Hub decides whether the display is
reachable and answers with a typed result.

The client carries the caller's identity and stamps its ``X-Lux-Client-*`` headers
on every request, so the Hub attributes each scene the CLI installs to the
repository the command ran in. Building the request is :class:`HttpCall`'s job and
reading the reply is :class:`RestReply`'s; the client only orchestrates the two.
luxd being unreachable is the one exceptional outcome and raises
:class:`HubUnavailableError`; the Hub's refusal of a reachable request comes back
as a typed :class:`OpError` in the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final
from urllib.parse import quote, urlencode

from punt_lux.cli_identity import CliIdentity
from punt_lux.hub_paths import HubPaths
from punt_lux.identity_headers import ClientHeaders
from punt_lux.operations import (
    OpError,
    Pong,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
)
from punt_lux.rest_http_call import HttpCall
from punt_lux.rest_loopback import LoopbackTransport
from punt_lux.rest_reply import RestReply
from punt_lux.rest_transport import HttpTransport, HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["LuxRestClient"]


@final
class LuxRestClient:
    """A thin typed client of luxd's REST routes, owned by the CLI layer."""

    _transport: HttpTransport
    _headers: dict[str, str]
    __slots__ = ("_headers", "_transport")

    def __new__(cls, transport: HttpTransport, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._headers = ClientHeaders.to_wire(identity)
        return self

    @classmethod
    def connect(cls, *, timeout: float = 2.0) -> Self:
        """Locate luxd's port and build a client, or raise if luxd is not running.

        The client's identity is derived from the invocation's context every run —
        a ``LUX_CLIENT`` override, else the git repository, else headless.
        """
        port = HubPaths().read_port()
        if port is None:
            raise HubUnavailableError(
                "luxd is not running. Run 'lux hub-install' to register the service."
            )
        return cls(LoopbackTransport(port, timeout), CliIdentity.resolve())

    def render(self, request: RenderRequest) -> SceneShown | OpError:
        """Install a whole scene through ``PUT /scenes/{scene_id}``.

        The scene id is a path segment, so it is percent-encoded: a cwd-derived
        id bearing spaces or reserved characters must not break the request-target.
        """
        segment = quote(request.scene_id, safe="")
        return self._send(HttpCall.write(f"/scenes/{segment}", request, self._headers))

    def render_table(self, request: RenderTableRequest) -> SceneShown | OpError:
        """Install a composed table scene through ``PUT /scenes/{scene_id}/table``.

        The Hub *constructs* the composition — search box, status combos, the grid,
        and a selection-bound detail panel wired through a shared
        ``FilteredTableModel`` — so its chrome runs Hub-side and stays live. A
        pre-composed tree pushed through ``render`` decodes to dead handlers; the
        table route carries the data and lets the Hub build the handlers.
        """
        segment = quote(request.scene_id, safe="")
        path = f"/scenes/{segment}/table"
        return self._send(HttpCall.write(path, request, self._headers))

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping through ``GET /display/ping``.

        A given ``wait`` rides through as the ``timeout`` query param (the
        display-leg budget); ``None`` omits it so luxd uses its standing budget.
        """
        suffix = f"?{urlencode({'timeout': wait})}" if wait is not None else ""
        call = HttpCall.read(f"/display/ping{suffix}", self._headers)
        return RestReply(self._transport.request(call)).read(Pong)

    def _send(self, call: HttpCall) -> SceneShown | OpError:
        """Send a scene-write call and read its reply as a ``SceneShown`` or error."""
        return RestReply(self._transport.request(call)).read(SceneShown)
