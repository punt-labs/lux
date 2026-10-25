# pyright: reportMissingModuleSource=false
"""ClientQueries -- answers the questions a client asks the display.

A ping, an introspection, a scene listing, a screenshot and a generic query change no
scene the display holds: each is a question, and each answer goes back through the one
door replies leave by (``ClientSender.reply_to_client``), so a reply the client misses
ends its connection instead of shifting every later one. This owns the handlers that
answer the generic queries too: the router is told, once, which object answers
``inspect_scene``, ``screenshot``, the window and theme facts, and a frame's dock
state. Extracted from :class:`~punt_lux.display.render_loop.RenderLoop`, which keeps
the messages that mutate scenes, menus and identity.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Self, final

from imgui_bundle import hello_imgui

from punt_lux.display.frame_commands import FrameCommands
from punt_lux.display.scene_inspector import SceneInspector
from punt_lux.display.screenshot_queue import ScreenshotQueue
from punt_lux.protocol import (
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    PingMessage,
    PongMessage,
    QueryRequest,
    ScreenshotRequest,
    UnknownMessage,
)
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable

    from punt_lux.display.client_sender import ClientSender
    from punt_lux.display.geometry import GeometryRecorder
    from punt_lux.display.query_dispatcher import QueryRouter
    from punt_lux.display.replica import SceneReplica
    from punt_lux.display.window_settings import WindowSettings
    from punt_lux.protocol.messages import Message

logger = logging.getLogger(__name__)

__all__ = ["ClientQueries"]


@final
class ClientQueries:
    """Answer ping, introspect, list-scenes, screenshot and generic-query messages."""

    _sender: ClientSender
    _query_router: QueryRouter
    _screenshots: ScreenshotQueue
    _start_time: float
    __slots__ = ("_query_router", "_screenshots", "_sender", "_start_time")

    def __new__(
        cls,
        *,
        sender: ClientSender,
        query_router: QueryRouter,
        scenes: SceneReplica,
        geometry: GeometryRecorder,
        settings: WindowSettings,
        record_error: Callable[[str, str, str], None],
    ) -> Self:
        self = super().__new__(cls)
        self._sender = sender
        self._query_router = query_router
        self._screenshots = ScreenshotQueue(record_error, sender)
        self._start_time = time.time()
        query_router.register_handler(
            "inspect_scene", SceneInspector(scenes=scenes, geometry=geometry).inspect
        )
        query_router.register_handler(
            "screenshot", self._screenshots.refuse_generic_query
        )
        query_router.register_handler("get_display_info", self._display_info)
        query_router.register_handler("get_window_settings", settings.window_report)
        query_router.register_handler("get_theme", settings.theme_report)
        query_router.register_handler(
            "set_frame_state", FrameCommands(scenes).set_state
        )
        return self

    def handle(self, sock: socket.socket, msg: Message) -> None:
        """Dispatch a question to its answer; an unknown kind is ignored."""
        if isinstance(msg, PingMessage):
            pong = PongMessage(ts=msg.ts, display_ts=time.time())
            self._sender.reply_to_client(sock, pong)
        elif isinstance(msg, IntrospectRequest):
            self._introspect(sock, msg)
        elif isinstance(msg, ListScenesRequest):
            self._list_scenes(sock)
        elif isinstance(msg, ScreenshotRequest):
            self._screenshots.request(sock)
        elif isinstance(msg, QueryRequest):
            self._query(sock, msg)
        elif isinstance(msg, UnknownMessage):
            logger.debug("Ignoring unknown message type %r", msg.raw_type)

    def after_swap(self) -> None:
        """Answer the queued screenshot, if any, now the frame has been swapped."""
        self._screenshots.after_swap()

    def _display_info(self, **_kwargs: object) -> dict[str, object]:
        """Return display server metadata."""
        params = hello_imgui.get_runner_params()
        size = params.app_window_params.window_geometry.size
        return {
            "backend": str(params.renderer_backend_type),
            "window_width": size[0],
            "window_height": size[1],
            "fps": round(hello_imgui.frame_rate(), 1),
            "pid": os.getpid(),
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "protocol_version": "1.0",
            "element_kinds": len(DEFAULT_ABC_REGISTRY.all_kinds),
        }

    def _introspect(self, sock: socket.socket, msg: IntrospectRequest) -> None:
        """Return the element tree for a scene to the requesting client."""
        qr = self._query_router.handle_query(
            "inspect_scene", {"scene_id": msg.scene_id}
        )
        if qr.error is not None:
            resp = IntrospectResponse(scene_id=msg.scene_id, error=qr.error)
        else:
            resp = IntrospectResponse(
                scene_id=msg.scene_id, elements=qr.result["elements"]
            )
        self._sender.reply_to_client(sock, resp)

    def _list_scenes(self, sock: socket.socket) -> None:
        """Return the list of active scenes and frames."""
        qr = self._query_router.handle_query("list_scenes", None)
        if qr.error is not None:
            resp = ListScenesResponse(error=qr.error)
        else:
            resp = ListScenesResponse(
                scenes=qr.result["scenes"], frames=qr.result["frames"]
            )
        self._sender.reply_to_client(sock, resp)

    def _query(self, sock: socket.socket, msg: QueryRequest) -> None:
        """Dispatch a generic QueryRequest to the registered handler."""
        resp = self._query_router.handle_query(msg.method, msg.params)
        self._sender.reply_to_client(sock, resp)
