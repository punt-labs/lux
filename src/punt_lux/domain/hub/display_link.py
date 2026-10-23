"""The Hub's connection to the display process.

:class:`DisplayLink` is a context manager over a Unix socket that performs
the ``ReadyMessage`` handshake and exposes typed methods for scenes, pings,
and queries. :meth:`set_fallback_handler` + :meth:`start_listener` enable
push-based dispatch on the listener thread; acks, pongs, and query responses route to
the queues :meth:`show`, :meth:`ping`, and :meth:`query` consume, and
:class:`ObserverMessage` frames queue as :class:`PolledEvent` for
:meth:`poll_event`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_replies import DisplayReplies
from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.protocol import (
    AckMessage,
    CallbackMenuMessage,
    HubManifestMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.polled_event import PolledEvent
    from punt_lux.protocol import Element

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_RECV_TIMEOUT", "DisplayLink"]

# The Hub-side budget for one display round-trip (ping / recv). A CLI reaching
# the display through luxd must keep its transport timeout above this.
DEFAULT_RECV_TIMEOUT = 5.0


class DisplayLink:
    """Client for the Lux display server.

    ``socket_path`` is the Unix socket path (``None`` uses the default).
    ``name`` is the identity this connection declares in its
    ``ConnectMessage``. ``kind="hub"`` triggers single-owner preemption plus
    a manifest (DES-068); ``"test"`` (default) is the read-only backdoor --
    a deliberately wrong-looking name, since the display rejects a
    ``SceneMessage`` sent under it. ``auto_spawn`` (default ``True``) spawns
    the display server when not running. ``connect_timeout`` bounds the wait
    for the display; ``recv_timeout`` is the default for :meth:`recv`.
    """

    _connection: DisplayConnection
    _replies: DisplayReplies

    def __new__(
        cls,
        socket_path: str | Path | None = None,
        *,
        name: str | None = None,
        kind: Literal["hub", "test"] = "test",
        auto_spawn: bool = True,
        connect_timeout: float = 5.0,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT,
        dialer: DisplayDialer | None = None,  # None = default AF_UNIX dialer (PY-TS-14)
    ) -> Self:
        self = super().__new__(cls)
        # An injected dialer (a cross-host CrossHostConnector built by
        # CrossHostEndpoint.dial) overrides the default AF_UNIX one.
        self._connection = DisplayConnection(
            dialer
            or HandshakeConnector(
                name=name, kind=kind, socket_path=socket_path, auto_spawn=auto_spawn
            ),
            connect_timeout,
        )
        self._replies = DisplayReplies(self._connection, recv_timeout)
        return self

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> DisplayLink:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- connection --------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Whether the client has an active socket connection."""
        return self._connection.is_open

    @property
    def listener_active(self) -> bool:
        """Whether the background listener thread is running."""
        return self._replies.listening

    @property
    def ready_message(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` received during handshake, or ``None``."""
        return self._connection.ready

    def connect(self) -> None:
        """Connect to the display server.

        No-op if already connected.  If *auto_spawn* is enabled and no
        display is running, spawns one first.  Blocks until the
        ``ReadyMessage``/``ConnectMessage`` handshake completes (delegated to
        :class:`HandshakeConnector`, which owns the socket-open and identity
        concern). The caller starts the listener.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start or the handshake times out.
        """
        if self._connection.is_open:
            return
        self._connection.open()

    def close(self) -> None:
        """Close the connection to the display server."""
        self.stop_listener()
        self._replies.end()

    # -- callback registration ---------------------------------------------

    def set_fallback_handler(
        self,
        handler: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Install the handler every interaction the display reports is given to.

        Called by the Hub to route display-side clicks through Hub-side element
        dispatch; with none installed an interaction is dropped.
        """
        self._replies.set_fallback(handler)

    # -- background listener -----------------------------------------------

    def start_listener(self) -> None:
        """Start the background listener thread.

        The listener reads incoming messages from the socket and
        dispatches them by kind: ``RemoteEventHandlerInvocation`` runs the
        fallback handler (none installed: it is dropped); ``ObserverMessage``
        payloads queue
        for :meth:`poll_event`; ``AckMessage``, ``PongMessage``, and
        ``QueryResponse`` route to their per-type queues for
        :meth:`show`, :meth:`ping`, and :meth:`query`.  Other message
        kinds are dropped with a debug log.

        Safe to call multiple times — no-ops if already running.
        """
        self._replies.start()

    def stop_listener(self) -> None:
        """Stop the background listener thread, if running."""
        self._replies.stop()

    # -- sending -----------------------------------------------------------

    def show(
        self,
        scene_id: str,
        elements: list[Element],
        *,
        title: str | None = None,
        layout: Literal["single", "rows", "columns", "grid"] = "single",
        frame_id: str | None = None,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
        frame_layout: Literal["tab", "stack"] | None = None,
    ) -> AckMessage | None:
        """Send a scene to the display and wait for acknowledgement.

        Every scene is framed: an omitted *frame_id* self-frames by *scene_id* (as
        the Hub does), so a bare ``show`` still lands in a named frame. Returns the
        :class:`AckMessage` or ``None`` on timeout.
        """
        presentation = ScenePresentation(
            frame_id=frame_id if frame_id is not None else scene_id,
            title=title,
            layout=layout,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
            frame_layout=frame_layout,
        )
        self.send_scene(presentation.message(scene_id, elements))
        return self._replies.typed(AckMessage, None)

    def send_scene(self, message: SceneMessage) -> None:
        """Send a built scene without waiting for an ack."""
        self._connection.send(message)

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        self._connection.send(MenuMessage(menus=menus))

    def set_callback_menus(self, submenus: list[dict[str, Any]]) -> None:
        """Replace the display's Clients menu (Hub-composed)."""
        self._connection.send(CallbackMenuMessage(submenus=submenus))

    def send_manifest(self, scene_ids: Sequence[str]) -> None:
        """Declare the Hub's complete live-scene set to the display (DES-068).

        Meaningful only for a ``kind="hub"`` connection, sent immediately
        after identifying and before any scene content. The display purges
        every scene it cannot attribute to this connection that the
        manifest does not name.
        """
        self._connection.send(HubManifestMessage(scene_ids=tuple(scene_ids)))

    def probe_alive(self, timeout: float) -> bool:
        """Return whether the display responded to a ping within ``timeout``.

        The :class:`DisplaySender` liveness probe the replicator's isolation
        loop calls between successive singleton sends, so a crash caused by
        scene N attributes to N (not N+1). A None pong (timed out) or any
        socket error the underlying send raises means the display did not
        respond in time; the caller treats that as a failure of the scene
        just sent.
        """
        return self.ping(timeout=timeout) is not None

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        """Send a ping and wait for the pong within ``timeout`` (else recv budget)."""
        self._connection.send(PingMessage(ts=time.time()))
        return self._replies.typed(PongMessage, timeout)

    def query(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> QueryResponse | None:
        """Send a generic query and wait for the response."""
        self._connection.send(QueryRequest(method=method, params=params or {}))
        return self._replies.typed(QueryResponse, timeout)

    # -- receiving ---------------------------------------------------------

    def poll_event(self, timeout: float | None = None) -> PolledEvent:
        """Block for the next subscribed business event (a :class:`PolledEvent`).

        Raises ``TimeoutError`` after ``timeout`` seconds (default
        ``recv_timeout``); requires an active listener (observer messages are
        push-only).
        """
        return self._replies.event(timeout)
