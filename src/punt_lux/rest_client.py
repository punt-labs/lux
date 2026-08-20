"""The public Python client of luxd's REST surface.

:class:`LuxRestClient` is the library surface a consumer imports — the CLI and any
downstream app use it rather than hand-rolling REST. It locates luxd's port,
speaks the operations request/result models over HTTP, and never touches the
display socket. It stamps the caller's ``X-Lux-Client-*`` identity headers on
every request, so each installed scene is attributed to the caller's repository;
:class:`HttpCall` builds the request and :class:`RestReply` reads the reply. An
unreachable luxd raises :class:`HubUnavailableError`; a reachable Hub's refusal
returns a typed :class:`OpError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final
from urllib.parse import quote, urlencode

from punt_lux.cli_identity import CliIdentity
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.hub_client import LuxHubClient
from punt_lux.hub_paths import HubPaths
from punt_lux.identity_headers import ClientHeaders
from punt_lux.operations import (
    ClientList,
    FrameRaise,
    MenuList,
    Ok,
    OpError,
    Pong,
    RecentErrors,
    RecentEvents,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
)
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
from punt_lux.operations.models.identity import Identified
from punt_lux.rest_client_display import DisplayRestOps
from punt_lux.rest_client_scenes import SceneRestOps
from punt_lux.rest_http_call import HttpCall
from punt_lux.rest_loopback import LoopbackTransport
from punt_lux.rest_reply import RestReply
from punt_lux.rest_transport import HttpTransport, HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.hub_client import CallbackHandler, ConnectHandler, EventHandler
    from punt_lux.operations import (
        Cleared,
        DisplayInfo,
        DisplayModeRequest,
        DisplayModeState,
        FrameStatePatch,
        InspectScope,
        RenderDashboardRequest,
        SceneInspection,
        SceneList,
        Scope,
        SetMenuRequest,
        SetThemeRequest,
        ThemeState,
        UpdateRequest,
        WindowSettings,
        WindowSettingsPatch,
    )

__all__ = ["LuxRestClient"]


@final
class LuxRestClient:
    """The public Python client of luxd — the library surface every consumer uses.

    A downstream app (vox, a headless tool) reaches the Hub through this typed
    client, not by hand-rolling REST, so it gets the same validation, typing, and
    identity behavior the CLI does. A daemon or app builds it with
    :meth:`for_identity`, declaring an EXPLICIT identity — who it is, an ``app``
    named for the service, not where it happened to run. A ``lux`` command uses
    :meth:`connect`, which derives a ``cli`` identity from its working context.
    """

    _transport: HttpTransport
    _identity: ClientIdentity
    _headers: dict[str, str]
    _scenes: SceneRestOps
    _display: DisplayRestOps
    __slots__ = ("_display", "_headers", "_identity", "_scenes", "_transport")

    def __new__(cls, transport: HttpTransport, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._identity = identity
        self._headers = ClientHeaders.to_wire(identity)
        self._scenes = SceneRestOps(transport, self._headers)
        self._display = DisplayRestOps(transport, self._headers)
        return self

    @classmethod
    def connect(cls, *, timeout: float = 2.0) -> Self:
        """The CLI convenience: build a client whose identity comes from the context.

        A ``lux`` command has no identity to declare, so one is derived from where it
        runs — a ``LUX_CLIENT`` override, else the git repository, else headless — as
        a ``cli`` identity. A daemon or app must NOT use this: it would be attributed
        by accident to wherever it started rather than to what it is. Such a caller
        declares itself with :meth:`for_identity`.
        """
        return cls.for_identity(CliIdentity.resolve(), timeout=timeout)

    @classmethod
    def for_identity(cls, identity: ClientIdentity, *, timeout: float = 2.0) -> Self:
        """Build a client that declares an EXPLICIT ``identity``, or raise if luxd down.

        The daemon and app path: a long-lived service names itself — an ``app`` with
        its own name, optionally its declared lease TTL — rather than deriving a
        ``cli`` identity from its working directory. A daemon that both pushes scenes
        and holds a listen connection builds one client here, then :meth:`listener`
        shares this identity so both legs resolve to a single connection.
        """
        port = HubPaths().read_port()
        if port is None:
            raise HubUnavailableError(
                "luxd is not running. Run 'lux hub-install' to register the service."
            )
        return cls(LoopbackTransport(port, timeout), identity)

    def listener(
        self,
        *,
        on_callback: CallbackHandler,
        on_event: EventHandler,
        on_connect: ConnectHandler | None = None,
    ) -> LuxHubClient:
        """Build a persistent listen client that shares this client's identity.

        Scene pushes stay on this REST client; the returned :class:`LuxHubClient`
        holds the WebSocket listen connection. Both carry one identity, so a callback
        this client registers over REST is delivered on the listener's stream.

        Pass ``on_connect`` to re-register those callbacks (and re-push scenes) after
        every handshake — the listener's internal reconnect restores subscriptions
        but not lease-expired callbacks, so the register-fresh work belongs here.
        """
        return LuxHubClient.connect(
            self._identity,
            on_callback=on_callback,
            on_event=on_event,
            on_connect=on_connect,
        )

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a whole scene through ``PUT /scenes/{scene_id}``.

        ``scope`` satisfies :class:`~punt_lux.commands._ports.SceneOps`'s call
        signature -- unused over REST, which composes scope from the
        ``X-Lux-Client-*`` headers already stamped on every request. Defaults
        to ``None`` so pre-Protocol callers keep working unchanged.
        """
        return self._scenes.render(request, scope=scope)

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a composed table scene through ``PUT /scenes/{scene_id}/table``."""
        return self._scenes.render_table(request, scope=scope)

    def register_callback(self, callback_id: str, label: str) -> Ok | OpError:
        """Register a menu callback for this identity through ``POST /menus/callbacks``.

        The daemon path: a client registers the callback it wants on the menu here,
        then receives the user's clicks on it over its :meth:`listener` stream — both
        under this client's identity, so the click routes back to the same session. A
        malformed id or label is reported as an ``OpError`` without a round-trip.
        """
        request = RegisterCallbackRequest.parse(callback_id=callback_id, label=label)
        if isinstance(request, OpError):
            return request
        call = HttpCall.post("/menus/callbacks", request, self._headers)
        return RestReply(self._transport.request(call)).read(Ok)

    def raise_frame(self, frame_id: str) -> FrameRaise | OpError:
        """Bring a frame to the front through ``POST /display/frames/{id}/raise``.

        The instant half of answering a click: a session whose board is already up
        makes it visible with this one call, before it goes looking for fresh data.
        A frame the display does not hold answers ``raised`` false — the caller's
        cue to push one — rather than an error.
        """
        segment = quote(frame_id, safe="")
        call = HttpCall.command(f"/display/frames/{segment}/raise", self._headers)
        return RestReply(self._transport.request(call)).read(FrameRaise)

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping through ``GET /display/ping``.

        A given ``wait`` rides through as the ``timeout`` query param (the
        display-leg budget); ``None`` omits it so luxd uses its standing budget.
        """
        suffix = f"?{urlencode({'timeout': wait})}" if wait is not None else ""
        call = HttpCall.read(f"/display/ping{suffix}", self._headers)
        return RestReply(self._transport.request(call)).read(Pong)

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Construct a dashboard scene through ``PUT /scenes/{scene_id}/dashboard``."""
        return self._scenes.render_dashboard(request, scope=scope)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch through ``PATCH /scenes/{scene_id}``."""
        return self._scenes.update(scene_id, request, scope=scope)

    def clear(self, *, scope: Scope) -> Cleared | OpError:
        """Clear every scene this identity owns through ``DELETE /scenes``."""
        return self._scenes.clear(scope=scope)

    def clear_scene(self, scene_id: str, *, scope: Scope) -> Cleared | OpError:
        """Clear one scene through ``DELETE /scenes/{scene_id}``."""
        return self._scenes.clear_scene(scope=scope, scene_id=scene_id)

    def list_scenes(self) -> SceneList:
        """List every live scene and frame through ``GET /scenes``."""
        return self._scenes.list_scenes()

    def inspect_scene(
        self, scene_id: str, *, scope: Scope, facts: InspectScope
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree through ``GET /scenes/{scene_id}``."""
        return self._scenes.inspect_scene(scene_id, scope=scope, facts=facts)

    def list_clients(self) -> ClientList:
        """List the Hub's sessions and their scopes through ``GET /clients``.

        ``SessionOps.list_clients`` promises a ``ClientList`` with no error
        case; a REST-level fault is raised rather than returned (PY-EH-8).
        """
        call = HttpCall.read("/clients", self._headers)
        result = RestReply(self._transport.request(call)).read(ClientList)
        if isinstance(result, OpError):
            raise RuntimeError(f"list_clients failed: {result.reason}")
        return result

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch | OpError
    ) -> Ok | OpError:
        """Change a frame's minimize state through ``PATCH /display/frames/{id}``."""
        if isinstance(patch, OpError):
            return patch
        segment = quote(frame_id, safe="")
        call = HttpCall.patch(f"/display/frames/{segment}", patch, self._headers)
        return RestReply(self._transport.request(call)).read(Ok)

    def list_menus(self) -> MenuList:
        """Return the Hub-authoritative menu bar through ``GET /menus``.

        ``MenuOps.list_menus`` promises a ``MenuList`` with no error case; a
        REST-level fault is raised rather than returned (PY-EH-8).
        """
        call = HttpCall.read("/menus", self._headers)
        result = RestReply(self._transport.request(call)).read(MenuList)
        if isinstance(result, OpError):
            raise RuntimeError(f"list_menus failed: {result.reason}")
        return result

    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Replace the Hub-owned menu bar through ``PUT /menus``."""
        if isinstance(request, OpError):
            return request
        call = HttpCall.write("/menus", request, self._headers)
        return RestReply(self._transport.request(call)).read(Ok)

    def get_display_info(self) -> DisplayInfo | OpError:
        """Return the display's backend/geometry through ``GET /display``."""
        return self._display.get_display_info()

    def get_theme(self) -> ThemeState | OpError:
        """Return the active theme through ``GET /display/theme``."""
        return self._display.get_theme()

    def set_theme(self, request: SetThemeRequest) -> ThemeState | OpError:
        """Switch the display theme through ``PUT /display/theme``."""
        return self._display.set_theme(request)

    def get_window_settings(self) -> WindowSettings | OpError:
        """Return the window's settings through ``GET /display/window``."""
        return self._display.get_window_settings()

    def set_window_settings(
        self, patch: WindowSettingsPatch
    ) -> WindowSettings | OpError:
        """Change window settings through ``PATCH /display/window``."""
        return self._display.set_window_settings(patch)

    def read_display_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read a project's display mode through ``GET /display-mode``."""
        return self._display.read_display_mode(repo)

    def write_display_mode(
        self, request: DisplayModeRequest
    ) -> DisplayModeState | OpError:
        """Write a project's display mode through ``PUT /display-mode``."""
        return self._display.write_display_mode(request)

    def identify(
        self, declaration: dict[str, object], *, scope: object
    ) -> Identified | OpError:
        """Confirm this client's declared identity, with no network round trip.

        REST has no dedicated identify endpoint: every request already carries
        this client's ``X-Lux-Client-*`` headers, and the Hub resolves the same
        identity from them on every write via ``RestCaller.resolve`` (the same
        ``session_identify`` command this method's counterpart runs Hub-side).
        A separate wire call here would declare nothing new, so this validates
        ``declaration`` against the client's own identity and confirms it.
        """
        del scope  # unused: REST composes scope from headers on every request
        parsed = ClientIdentity.model_validate(
            {**declaration, "kind": declaration.get("kind", self._identity.kind)}
        )
        if parsed != self._identity:
            return OpError(
                code="invalid_request",
                reason=(
                    "declared identity does not match this REST client's "
                    "identity headers"
                ),
            )
        return Identified(identity=self._identity)

    def list_recent_events(self, count: int) -> RecentEvents | OpError:
        """Return recent interactions through ``GET /events``."""
        query = urlencode({"count": count})
        call = HttpCall.read(f"/events?{query}", self._headers)
        return RestReply(self._transport.request(call)).read(RecentEvents)

    def list_errors(self, count: int) -> RecentErrors | OpError:
        """Return recent errors through ``GET /errors``."""
        query = urlencode({"count": count})
        call = HttpCall.read(f"/errors?{query}", self._headers)
        return RestReply(self._transport.request(call)).read(RecentErrors)

    def _send(self, call: HttpCall) -> SceneShown | OpError:
        """Send a scene-write call and read its reply as a ``SceneShown`` or error."""
        return RestReply(self._transport.request(call)).read(SceneShown)
