"""The operations layer — the single home of every capability's logic.

Each capability is one typed operation on a concern class. The :class:`Operations`
facade composes those classes so one caller — an MCP adapter, a REST route, or a
test — has one object to call. ``production`` wires the process singletons;
``for_store`` binds a caller-supplied store so a test drives the real operations
without the running process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub import client_registry, hub, hub_display
from punt_lux.domain.hub.replicator_instance import hub_replicator
from punt_lux.operations.config import DisplayModeOperations
from punt_lux.operations.conveniences import ConvenienceOperations
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
from punt_lux.operations.ports import HubPorts
from punt_lux.operations.pubsub import PubSubOperations
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope as ScopeType

__all__ = [
    "Cleared",
    "DisplayModeRequest",
    "DisplayModeState",
    "HubPorts",
    "OpError",
    "Operations",
    "PublishRequest",
    "Published",
    "Received",
    "RenderDashboardRequest",
    "RenderRequest",
    "RenderTableRequest",
    "SceneShown",
    "Scope",
    "Subscribed",
    "Unsubscribed",
    "UpdateRequest",
]


class Operations:
    """A single object exposing every capability, composed from concern classes."""

    _scenes: SceneOperations
    _conveniences: ConvenienceOperations
    _pubsub: PubSubOperations
    _config: DisplayModeOperations
    __slots__ = ("_config", "_conveniences", "_pubsub", "_scenes")

    def __new__(
        cls,
        *,
        scenes: SceneOperations,
        conveniences: ConvenienceOperations,
        pubsub: PubSubOperations,
        config: DisplayModeOperations,
    ) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        self._conveniences = conveniences
        self._pubsub = pubsub
        self._config = config
        return self

    @classmethod
    def production(cls, ports: HubPorts) -> Self:
        """Wire the operations against the process's Hub singletons."""
        return cls.for_store(hub_display, hub_replicator, ports)

    @classmethod
    def for_store(
        cls, display: HubDisplay, replicator: DirtyMarker, ports: HubPorts
    ) -> Self:
        """Wire scene operations against a given store; pub-sub and config stay live."""
        scenes = SceneOperations(display, replicator, ports.element_factory)
        return cls(
            scenes=scenes,
            conveniences=ConvenienceOperations(scenes),
            pubsub=PubSubOperations(hub, ports.ensure_writer, ports.next_event),
            config=DisplayModeOperations(client_registry),
        )

    def render(
        self, request: RenderRequest | OpError, *, scope: ScopeType
    ) -> SceneShown | OpError:
        """Install a whole scene."""
        return self._scenes.render(request, scope=scope)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: ScopeType
    ) -> SceneShown | OpError:
        """Apply a patch batch to a scene."""
        return self._scenes.update(scene_id, request, scope=scope)

    def clear(self, *, scope: ScopeType) -> Cleared:
        """Clear every scene the caller owns."""
        return self._scenes.clear(scope=scope)

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: ScopeType
    ) -> SceneShown | OpError:
        """Render a filterable table scene."""
        return self._conveniences.render_table(request, scope=scope)

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: ScopeType
    ) -> SceneShown | OpError:
        """Render a dashboard scene."""
        return self._conveniences.render_dashboard(request, scope=scope)

    def subscribe(self, topic: str, *, scope: ScopeType) -> Subscribed:
        """Subscribe the caller's session to a topic."""
        return self._pubsub.subscribe(topic, scope=scope)

    def unsubscribe(self, topic: str, *, scope: ScopeType) -> Unsubscribed:
        """Unsubscribe the caller's session from a topic."""
        return self._pubsub.unsubscribe(topic, scope=scope)

    def publish(
        self, topic: str, request: PublishRequest, *, scope: ScopeType
    ) -> Published:
        """Publish a payload to a topic's subscribers."""
        return self._pubsub.publish(topic, request, scope=scope)

    def receive(self, *, scope: ScopeType) -> Received:
        """Take the next business event for the caller's session."""
        return self._pubsub.receive(scope=scope)

    def read_display_mode(self, repo: str) -> DisplayModeState:
        """Read a project's display mode."""
        return self._config.read_display_mode(repo)

    def write_display_mode(self, request: DisplayModeRequest) -> DisplayModeState:
        """Write a project's display mode."""
        return self._config.write_display_mode(request)
