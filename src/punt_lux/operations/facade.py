"""The Operations facade — one object exposing every capability.

Composes the concern classes so a single caller — MCP, REST, or a test — has
one object to call. Every collaborator is injected into ``for_store``, so
nothing here binds the running process at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.callbacks import CallbackOperations
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.concerns import OperationsConcerns
from punt_lux.operations.config import DisplayModeOperations
from punt_lux.operations.conveniences import ConvenienceOperations
from punt_lux.operations.display_control import DisplayControlOperations
from punt_lux.operations.frame_closing import FrameCloser
from punt_lux.operations.identity import IdentityOperations
from punt_lux.operations.menus import MenuOperations
from punt_lux.operations.models.inspect_scope import HUB_ONLY, InspectScope
from punt_lux.operations.pubsub import PubSubOperations
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scene_deps import SceneOperationsDeps
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.timing import Timed

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_hold import CallbackRouter
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.operations.models import (
        Cleared,
        DisplayModeState,
        OpError,
        Published,
        PublishRequest,
        Received,
        RenderDashboardRequest,
        RenderRequest,
        RenderTableRequest,
        SceneShown,
        Subscribed,
        Unsubscribed,
        UpdateRequest,
    )
    from punt_lux.operations.models.callbacks import (
        RegisterCallbackRequest,
    )
    from punt_lux.operations.models.display_frames import FrameStates
    from punt_lux.operations.models.display_info import DisplayInfo
    from punt_lux.operations.models.display_probe import Pong, Screenshot
    from punt_lux.operations.models.display_state import DisplayStateSnapshot
    from punt_lux.operations.models.identity import Identified
    from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
    from punt_lux.operations.models.query_clients import ClientList
    from punt_lux.operations.models.query_errors import RecentErrors
    from punt_lux.operations.models.query_events import RecentEvents
    from punt_lux.operations.models.query_inspection import SceneInspection
    from punt_lux.operations.models.query_scenes import SceneList
    from punt_lux.operations.models.theme import ThemeState
    from punt_lux.operations.models.window import WindowSettings
    from punt_lux.operations.ports import DirtyMarker, HubPorts
    from punt_lux.operations.scope import Scope

__all__ = ["Operations"]


@final
class Operations:
    """A single object exposing every capability, composed from concern classes."""

    _scenes: SceneOperations
    _conveniences: ConvenienceOperations
    _pubsub: PubSubOperations
    _config: DisplayModeOperations
    _display: DisplayControlOperations
    _queries: QueryOperations
    _menus: MenuOperations
    _identity: IdentityOperations
    _callbacks: CallbackOperations
    _frame_closer: FrameCloser
    __slots__ = (
        "_callbacks",
        "_config",
        "_conveniences",
        "_display",
        "_frame_closer",
        "_identity",
        "_menus",
        "_pubsub",
        "_queries",
        "_scenes",
    )

    def __new__(cls, concerns: OperationsConcerns) -> Self:
        self = super().__new__(cls)
        self._scenes = concerns.scenes
        self._conveniences = ConvenienceOperations(concerns.scenes)
        self._pubsub = concerns.pubsub
        self._config = concerns.config
        self._display = concerns.display
        self._queries = concerns.queries
        self._menus = concerns.menus
        self._identity = concerns.identity
        self._callbacks = concerns.callbacks
        self._frame_closer = concerns.frame_closer
        return self

    @classmethod
    def for_store(
        cls,
        display: HubDisplay,
        replicator: DirtyMarker,
        *,
        hub: Hub,
        menu_registry: HubMenuRegistry,
        callback_router: CallbackRouter,
        ports: HubPorts,
    ) -> Self:
        """Wire every concern class from injected collaborators — no singletons."""
        deps = SceneOperationsDeps(display, replicator, ports.element_factory, hub)
        scenes = SceneOperations(deps)
        callbacks = CallbackOperations(display.clients, callback_router, replicator)
        clients = ClientListing(display, hub, ports.inbox_depth)
        queries = QueryOperations(display, ports.display_port, clients)
        return cls(
            OperationsConcerns(
                scenes=scenes,
                pubsub=PubSubOperations(hub, display.clients, ports),
                config=DisplayModeOperations(),
                display=DisplayControlOperations(ports.display_port),
                queries=queries,
                menus=MenuOperations(menu_registry, replicator, callbacks),
                identity=IdentityOperations(display),
                callbacks=callbacks,
                frame_closer=FrameCloser(display, replicator),
            )
        )

    @Timed("render")
    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install a whole scene."""
        return self._scenes.render(request, scope=scope)

    @Timed("update")
    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to a scene."""
        return self._scenes.update(scene_id, request, scope=scope)

    @Timed("clear")
    def clear(self, *, scope: Scope) -> Cleared | OpError:
        """Clear every scene the caller owns."""
        return self._scenes.clear(scope=scope)

    @Timed("clear_scene")
    def clear_scene(self, *, scope: Scope, scene_id: str) -> Cleared | OpError:
        """Clear just ``scene_id``; unknown or unowned is an error, not a false pass."""
        return self._scenes.clear(scope=scope, scene_id=scene_id)

    @Timed("render_table")
    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a filterable table scene."""
        return self._conveniences.render_table(request, scope=scope)

    @Timed("render_dashboard")
    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a dashboard scene."""
        return self._conveniences.render_dashboard(request, scope=scope)

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed:
        """Subscribe the caller's session to a topic."""
        return self._pubsub.subscribe(topic, scope=scope)

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed:
        """Unsubscribe the caller's session from a topic."""
        return self._pubsub.unsubscribe(topic, scope=scope)

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published:
        """Publish a payload to a topic's subscribers."""
        return self._pubsub.publish(topic, request, scope=scope)

    def receive(self, *, scope: Scope) -> Received:
        """Take the next business event for the caller's session."""
        return self._pubsub.receive(scope=scope)

    def read_display_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read a project's display mode."""
        return self._config.read_display_mode(repo)

    def get_display_info(self) -> DisplayInfo | OpError:
        """Return the display's backend, geometry, frame rate, and identity."""
        return self._display.get_display_info()

    def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        return self._display.get_theme()

    def get_window_settings(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        return self._display.get_window_settings()

    def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer and return the image path."""
        return self._display.screenshot()

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a ping bounded by ``wait`` seconds (``None`` uses the budget)."""
        return self._display.ping(wait)

    @Timed("list_frames")
    def list_frames(self) -> FrameStates | OpError:
        """List every frame the display holds and where it is showing each one."""
        return self._display.list_frames()

    @Timed("close_frame")
    def close_frame(self, frame_id: str, *, scope: Scope) -> Ok | OpError:
        """Close the caller's own frame; the ``frame_close`` command calls this."""
        return self._frame_closer.close(frame_id, scope.connection_id)

    def inspect_scene(
        self, scene_id: str, *, scope: Scope, facts: InspectScope = HUB_ONLY
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree (DES-086, no admin path); ``facts`` adds
        proxied geometry."""
        return self._queries.inspect_scene(scene_id, scope, facts)

    def list_scenes(self, facts: InspectScope = HUB_ONLY) -> SceneList:
        """List every live scene and frame; ``facts`` adds proxied visibility."""
        return self._queries.list_scenes(facts)

    def list_clients(self) -> ClientList:
        """List the Hub's sessions and their scopes."""
        return self._queries.list_clients()

    def list_recent_events(self, count: int) -> RecentEvents | OpError:
        """Return the display's recent interactions, proxied."""
        return self._queries.list_recent_events(count)

    def list_errors(self, count: int) -> RecentErrors | OpError:
        """Return the display's recent errors, proxied."""
        return self._queries.list_errors(count)

    def get_display_state(self, *, scope: Scope) -> DisplayStateSnapshot | OpError:
        """Return the caller's own widget/frame state, proxied."""
        return self._queries.display_state(scope)

    @Timed("set_menu")
    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Replace the Hub-owned menu bar; the replicator pushes it."""
        return self._menus.set_menu(request)

    def list_menus(self) -> MenuList:
        """Return the Hub-authoritative menu bar, including the callback submenus."""
        return self._menus.list_menus()

    @Timed("register_callback")
    def register_callback(
        self, request: RegisterCallbackRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Register a menu callback for the caller's session; the replicator pushes.

        Registration is the whole client-facing surface of the callback model.
        Routing a click (``invoke_callback``) stays Hub-internal — the display
        dispatches clicks, not a client — and delivering one is the listen leg's
        job, so a registered session is pushed its clicks rather than offered a
        read to poll.
        """
        return self._callbacks.register_callback(request, scope=scope)

    def pending_callbacks(self, *, scope: Scope) -> tuple[CallbackInvocation, ...]:
        """Return the caller's held callback invocations without clearing them."""
        return self._callbacks.pending_callbacks(scope=scope)

    def identify(
        self, declaration: dict[str, object], *, scope: Scope
    ) -> Identified | OpError:
        """Record the caller's declared identity, or reject a malformed one."""
        return self._identity.identify(declaration, scope=scope)

    def identity_of(self, *, scope: Scope) -> ClientIdentity | None:
        """Return the identity already declared for ``scope``, or ``None``."""
        return self._identity.current(scope)

    def drop_session(self) -> None:
        """Re-push the menu after a session departs so its submenu vanishes."""
        self._callbacks.drop_session()
