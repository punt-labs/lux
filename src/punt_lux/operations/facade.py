"""The Operations facade — one object exposing every capability.

The facade composes the concern classes so a single caller — an MCP adapter, a
REST route, or a test — has one object to call. It imports no process singletons
at module scope: every collaborator (store, replicator, hub, client registry,
display connection) is injected into ``for_store`` by the composition root in the
presentation layer, so nothing here binds the running process at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.config import DisplayModeOperations
from punt_lux.operations.conveniences import ConvenienceOperations
from punt_lux.operations.display_control import DisplayControlOperations
from punt_lux.operations.menus import MenuOperations
from punt_lux.operations.pubsub import PubSubOperations
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scenes import SceneOperations

if TYPE_CHECKING:
    from punt_lux.domain.hub.clients import ClientRegistry
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.models import (
        Cleared,
        DisplayModeRequest,
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
    from punt_lux.operations.models.display_info import DisplayInfo
    from punt_lux.operations.models.display_probe import Pong, Screenshot
    from punt_lux.operations.models.display_write import DisplayAck, FrameStatePatch
    from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
    from punt_lux.operations.models.menus import MenuAction
    from punt_lux.operations.models.query_clients import ClientList
    from punt_lux.operations.models.query_errors import RecentErrors
    from punt_lux.operations.models.query_events import RecentEvents
    from punt_lux.operations.models.query_inspection import SceneInspection
    from punt_lux.operations.models.query_scenes import SceneList
    from punt_lux.operations.models.theme import SetThemeRequest, ThemeState
    from punt_lux.operations.models.window import WindowSettings, WindowSettingsPatch
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
    __slots__ = (
        "_config",
        "_conveniences",
        "_display",
        "_menus",
        "_pubsub",
        "_queries",
        "_scenes",
    )

    def __new__(
        cls,
        *,
        scenes: SceneOperations,
        conveniences: ConvenienceOperations,
        pubsub: PubSubOperations,
        config: DisplayModeOperations,
        display: DisplayControlOperations,
        queries: QueryOperations,
        menus: MenuOperations,
    ) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        self._conveniences = conveniences
        self._pubsub = pubsub
        self._config = config
        self._display = display
        self._queries = queries
        self._menus = menus
        return self

    @classmethod
    def for_store(
        cls,
        display: HubDisplay,
        replicator: DirtyMarker,
        *,
        hub: Hub,
        client_registry: ClientRegistry,
        menu_registry: HubMenuRegistry,
        ports: HubPorts,
        display_port: DisplayPort,
    ) -> Self:
        """Wire every concern class from injected collaborators — no singletons."""
        scenes = SceneOperations(display, replicator, ports.element_factory)
        return cls(
            scenes=scenes,
            conveniences=ConvenienceOperations(scenes),
            pubsub=PubSubOperations(hub, ports.ensure_writer, ports.next_event),
            config=DisplayModeOperations(client_registry),
            display=DisplayControlOperations(display_port),
            queries=QueryOperations(display, hub, display_port),
            menus=MenuOperations(menu_registry, replicator),
        )

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install a whole scene."""
        return self._scenes.render(request, scope=scope)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to a scene."""
        return self._scenes.update(scene_id, request, scope=scope)

    def clear(self, *, scope: Scope) -> Cleared:
        """Clear every scene the caller owns."""
        return self._scenes.clear(scope=scope)

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a filterable table scene."""
        return self._conveniences.render_table(request, scope=scope)

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

    def write_display_mode(
        self, request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Write a project's display mode."""
        return self._config.write_display_mode(request)

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

    def ping(self, *, now: float) -> Pong | OpError:
        """Round-trip a ping and return the elapsed time."""
        return self._display.ping(now=now)

    def set_theme(self, request: SetThemeRequest | OpError) -> DisplayAck | OpError:
        """Switch the display theme."""
        return self._display.set_theme(request)

    def set_window_settings(
        self, patch: WindowSettingsPatch | OpError
    ) -> DisplayAck | OpError:
        """Change the provided window settings."""
        return self._display.set_window_settings(patch)

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch | OpError
    ) -> DisplayAck | OpError:
        """Change a frame's minimize state."""
        return self._display.set_frame_state(frame_id, patch)

    def inspect_scene(
        self, scene_id: str, *, want_mirror: bool = False
    ) -> SceneInspection | OpError:
        """Return a scene's element tree from the authoritative store."""
        return self._queries.inspect_scene(scene_id, want_mirror=want_mirror)

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        return self._queries.list_scenes()

    def list_clients(self, *, now: float) -> ClientList:
        """List the Hub's sessions and their scopes."""
        return self._queries.list_clients(now=now)

    def list_recent_events(self, count: int) -> RecentEvents | OpError:
        """Return the display's recent interactions, proxied."""
        return self._queries.list_recent_events(count)

    def list_errors(self, count: int) -> RecentErrors | OpError:
        """Return the display's recent errors, proxied."""
        return self._queries.list_errors(count)

    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Replace the Hub-owned menu bar; the replicator pushes it."""
        return self._menus.set_menu(request)

    def register_menu_item(self, action: MenuAction, *, scope: Scope) -> Ok:
        """Register a tool item for the caller's session; the replicator pushes."""
        return self._menus.register_menu_item(action, scope=scope)

    def list_menus(self) -> MenuList:
        """Return the Hub-authoritative menu bar."""
        return self._menus.list_menus()
