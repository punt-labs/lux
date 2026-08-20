"""Per-family ops-surface Protocols and the ``Ctx`` that carries them.

Each Protocol names exactly the methods the commands in one family call.
Splitting the ops surface family-by-family keeps every stub test small (the
scene commands' ``StubSceneOps`` implements ``SceneOps`` and nothing else),
and lets a narrow transport such as :class:`LuxRestClient` satisfy only the
families it exposes. ``Operations`` (luxd's typed facade) satisfies every
family structurally. ``Ctx`` lives here beside them so a command imports the
Protocol and the context it wraps from one module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.operations import (
        Cleared,
        ClientList,
        DisplayInfo,
        DisplayModeRequest,
        DisplayModeState,
        InspectScope,
        MenuList,
        Ok,
        OpError,
        Pong,
        RenderDashboardRequest,
        RenderRequest,
        RenderTableRequest,
        SceneInspection,
        SceneList,
        SceneShown,
        Scope,
        SetThemeRequest,
        ThemeState,
        UpdateRequest,
        WindowSettings,
        WindowSettingsPatch,
    )
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest
    from punt_lux.operations.models.display_probe import Screenshot
    from punt_lux.operations.models.display_write import FrameStatePatch
    from punt_lux.operations.models.identity import Identified
    from punt_lux.operations.models.menu_results import SetMenuRequest
    from punt_lux.operations.models.pubsub import PublishRequest, Received
    from punt_lux.operations.models.pubsub_acks import (
        Published,
        Subscribed,
        Unsubscribed,
    )
    from punt_lux.operations.models.query_errors import RecentErrors
    from punt_lux.operations.models.query_events import RecentEvents


@runtime_checkable
class PingOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.ping` reads."""

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping bounded by ``wait`` seconds."""
        ...


@runtime_checkable
class SceneOps(Protocol):
    """The ops surface the scene commands read."""

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install a whole scene."""
        ...

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to a scene."""
        ...

    def clear_scene(self, *, scope: Scope, scene_id: str) -> Cleared | OpError:
        """Clear just ``scene_id``."""
        ...

    def clear(self, *, scope: Scope) -> Cleared | OpError:
        """Clear every scene the caller owns."""
        ...

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a filterable table scene."""
        ...

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a dashboard scene."""
        ...

    def inspect_scene(
        self, scene_id: str, *, scope: Scope, facts: InspectScope
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree."""
        ...

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        ...


@runtime_checkable
class FrameOps(Protocol):
    """The ops surface the frame commands read."""

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch | OpError
    ) -> Ok | OpError:
        """Change a frame's minimize state."""
        ...


@runtime_checkable
class MenuOps(Protocol):
    """The ops surface the menu commands read."""

    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Replace the Hub-owned menu bar; the replicator pushes it."""
        ...

    def list_menus(self) -> MenuList:
        """Return the Hub-authoritative menu bar."""
        ...


@runtime_checkable
class SessionOps(Protocol):
    """The ops surface the session commands read."""

    def list_clients(self) -> ClientList:
        """List the Hub's sessions and their scopes."""
        ...

    def identify(
        self, declaration: dict[str, object], *, scope: Scope
    ) -> Identified | OpError:
        """Record the caller's declared identity, or reject a malformed one."""
        ...


@runtime_checkable
class CallbackRegisterOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.callback_register` reads.

    Split from the pending-invocations read (below) because the two have
    different reachable transports: ``register_callback`` has a REST route
    and a REST-backed client can implement it; ``pending_callbacks`` does
    not (its delivery is the listen leg's ``take`` drain, which a stateless
    REST request cannot bind to) -- see :class:`CallbackPendingOps`.
    """

    def register_callback(
        self, request: RegisterCallbackRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Register a menu callback for the caller's session."""
        ...


@runtime_checkable
class CallbackPendingOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.callback_pending` reads.

    No REST route exists or can exist for this read (ratified:
    ``tests/rest/test_app.py`` ``_MCP_ONLY``) -- delivery is the listen
    leg's drain, which only the in-process ``Operations`` facade can serve.
    """

    def pending_callbacks(self, *, scope: Scope) -> tuple[CallbackInvocation, ...]:
        """Return the caller's held callback invocations without clearing them."""
        ...


@runtime_checkable
class TopicOps(Protocol):
    """The ops surface the topic commands read."""

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published:
        """Fan a payload out to a topic's subscribers."""
        ...

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed:
        """Subscribe the caller's session to a topic."""
        ...

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed:
        """Unsubscribe the caller's session from a topic."""
        ...

    def receive(self, *, scope: Scope) -> Received:
        """Take the next business event for the caller's session."""
        ...


@runtime_checkable
class EventOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.event_ls` reads."""

    def list_recent_events(self, count: int) -> RecentEvents | OpError:
        """Return the display's recent interactions."""
        ...


@runtime_checkable
class ErrorOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.error_ls` reads."""

    def list_errors(self, count: int) -> RecentErrors | OpError:
        """Return the display's recent errors."""
        ...


@runtime_checkable
class DisplayInfoOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.display_info` reads."""

    def get_display_info(self) -> DisplayInfo | OpError:
        """Return the display's backend, geometry, frame rate, and identity."""
        ...


@runtime_checkable
class ThemeOps(Protocol):
    """The ops surface the display-theme commands read."""

    def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        ...

    def set_theme(self, request: SetThemeRequest | OpError) -> ThemeState | OpError:
        """Switch the display theme and return the new theme state."""
        ...


@runtime_checkable
class WindowOps(Protocol):
    """The ops surface the display-window commands read."""

    def get_window_settings(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        ...

    def set_window_settings(
        self, patch: WindowSettingsPatch | OpError
    ) -> WindowSettings | OpError:
        """Change the provided window settings and return the new settings."""
        ...


@runtime_checkable
class DisplayModeOps(Protocol):
    """The ops surface the display-mode config commands read."""

    def read_display_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read a project's display mode."""
        ...

    def write_display_mode(
        self, request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Write a project's display mode."""
        ...


@runtime_checkable
class ScreenshotOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.display_screenshot` reads."""

    def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer and return the image path."""
        ...


@dataclass(frozen=True, slots=True)
class Ctx[OpsT]:
    """Collaborators shared by every command.

    Attributes:
        ops: The ops family surface this command reads -- narrowed per command
            (``Ctx[SceneOps]``, ``Ctx[PingOps]``, ...) so a stub test and a
            remote transport each need only satisfy the family they touch.
            ``Ctx`` is invariant in ``OpsT`` (PEP 695 gives no variance
            keyword), so build it either inline as a call argument or with an
            explicit ``Ctx[SomeOps]`` annotation on the assignment.
        identity: The caller's declared identity (DES-086). Store lookups key
            by ``identity.name`` / ``identity.repo`` / ``identity.agent``.
    """

    ops: OpsT
    identity: ClientIdentity
