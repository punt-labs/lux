# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""The ImGui render loop, with non-blocking Unix socket IPC.

Listens on a Unix domain socket for protocol messages and renders scenes
using imgui-bundle. Socket I/O is polled every frame via ``select()`` with
zero timeout — no threads, no asyncio.

This module imports Pillow at module level but defers ImGui and OpenGL
imports to method bodies. It can be imported by unit tests (for state
machine testing) but ``run()`` requires a GPU-capable environment.
"""

from __future__ import annotations

import dataclasses
import logging
import platform
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from PIL import Image

from punt_lux.display.auto_click import AutoClicker
from punt_lux.display.dock_bar import DockBar
from punt_lux.display.exit_signal import ExitSignal
from punt_lux.display.frame_commands import FrameCommands
from punt_lux.display.frame_placement import FramePlacement
from punt_lux.display.frame_tiling import FrameTiling
from punt_lux.display.glfw_window import GlfwWindow
from punt_lux.display.hub_reconciliation import HubReconciliation
from punt_lux.display.idle_screen import render_idle
from punt_lux.display.interaction_delivery import InteractionDelivery
from punt_lux.display.macos import set_regular_activation_policy
from punt_lux.display.markdown_font import MarkdownFont
from punt_lux.display.paint_clock import PaintClock
from punt_lux.display.pending_interactions import PendingInteractions
from punt_lux.display.query_dispatcher import QueryRouter
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.replica import Frame, SceneReplica, WidgetState
from punt_lux.display.replica.menu_replica import MenuReplica
from punt_lux.display.scene_inspector import SceneInspector
from punt_lux.display.socket_server import SocketListener
from punt_lux.display.texture_cache import TextureCache
from punt_lux.display.window_chrome import WindowChrome
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    AckMessage,
    CallbackMenuMessage,
    ConnectMessage,
    HubManifestMessage,
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    MenuMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    RemoteEventHandlerInvocation,
    SceneMessage,
    ScreenshotRequest,
    ScreenshotResponse,
    ThemeMessage,
    UnknownMessage,
)
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

# Sentinel fd for scenes whose owning client has disconnected and no other
# client remains in the frame.  The scene persists until the user closes the
# frame or a new client adopts it.
_ORPHAN_FD = -1

# Total wall-clock a single frame's synchronous sends (Acks, Pongs, query
# responses) may spend waiting on a backpressured Hub. Well below the 1 s ping
# timeout and the ~2 s macOS "not responding" threshold, so a slow-but-alive
# peer never wedges the render thread long enough to trip either. Individual
# sends past the budget are deferred by the caller, not blocked.
_FRAME_SEND_BUDGET = 0.1


class RenderLoop:
    """The ImGui render loop, with non-blocking Unix socket IPC."""

    _socket_path: Path
    _socket_listener: SocketListener
    _scenes: SceneReplica
    _event_queue: list[RemoteEventHandlerInvocation]
    _interaction_delivery: InteractionDelivery
    _pending: PendingInteractions
    _textures: TextureCache
    _paint_clock: PaintClock
    _widget_state: WidgetState
    _menus: MenuReplica
    _themes: list[Any]
    _decorated: bool
    _opacity: float
    _font_scale: float
    _fit_all_frames: bool
    _screenshot_pending: socket.socket | None
    _test_auto_click: bool
    _start_time: float
    _current_theme: str
    _current_scene_id: str | None
    _query_router: QueryRouter
    _scene_inspector: SceneInspector
    _display_paths: DisplayPaths
    _imgui_renderer_factory: ImGuiRendererFactory
    _luxd_factory: Any  # JsonElementFactory, declared Any to avoid an import cycle
    _hub_reconciliation: HubReconciliation
    _exit_signal: ExitSignal

    def __new__(
        cls,
        socket_path: str | None = None,
        *,
        test_auto_click: bool = False,
    ) -> Self:
        self = super().__new__(cls)
        paths = DisplayPaths(Path(socket_path) if socket_path else None)
        self._socket_path = paths.socket_path
        self._display_paths = paths
        self._scenes = SceneReplica(
            on_scene_replaced=self._drain_stale_events,
        )
        self._themes = []
        self._decorated = True
        self._opacity = 1.0
        self._font_scale = 1.1
        self._fit_all_frames = False
        self._current_theme = "imgui_colors_dark"
        self._menus = MenuReplica(
            emit_event=self._emit_event,
            on_theme_selected=self._apply_theme,
            on_decorated_toggled=self._on_decorated_toggled,
            on_opacity_changed=self._on_opacity_changed,
            on_font_scale_changed=self._on_font_scale_changed,
            get_themes=lambda: self._themes,
            get_decorated=lambda: self._decorated,
            get_opacity=lambda: self._opacity,
            get_font_scale=lambda: self._font_scale,
            get_frames=lambda: self._scenes.frames,
            on_clear_all=self._clear_all,
            on_fit_all=self._request_fit_all,
            on_raise_frame=self._raise_frame,
            chrome=WindowChrome(),
        )
        # QueryRouter must be created before SocketListener so that
        # the on_error callback is available.
        self._query_router = QueryRouter(
            scenes=self._scenes,
            get_client_names=lambda: self._socket_listener.client_names,
            get_client_connect_times=lambda: self._socket_listener.client_connect_times,
            get_agent_menus=lambda: self._menus.agent_menus,
            get_callback_menus=lambda: self._menus.callback_menus,
        )
        self._socket_listener = SocketListener(
            on_message=self._handle_message,
            on_client_disconnected=self._on_client_disconnected,
            on_error=self._query_router.record_error,
        )
        self._interaction_delivery = InteractionDelivery(
            socket_listener=self._socket_listener,
            scenes=self._scenes,
        )
        self._hub_reconciliation = HubReconciliation(
            socket_listener=self._socket_listener,
            scenes=self._scenes,
            record_error=self._query_router.record_error,
        )
        # Bind a fail-loud decode factory to the shared container-dispatch
        # target. Inbound scenes cross as pickles (SceneCodec), so the display
        # never JSON-decodes a tree and this is not on the scene path; it is the
        # sentinel for any JSON element decode here. The Display may not own
        # business publish, so a container decoded through it fails loud
        # (RaisingRendererFactory + RaisingPublishSink), never running locally.
        from punt_lux.display.replica.emit import NoOpEmit
        from punt_lux.protocol.element_factory import JsonElementFactory
        from punt_lux.protocol.elements.container_dispatch import (
            dispatch as _container_dispatch,
        )
        from punt_lux.protocol.raising_publish_sink import RaisingPublishSink

        self._luxd_factory = JsonElementFactory(
            renderer_factory=RaisingRendererFactory(),
            emit=NoOpEmit(),
            publish_sink=cast(
                "Any",
                RaisingPublishSink("RenderLoop._luxd_factory"),
            ),
        )
        _container_dispatch.install_from_dict(self._luxd_factory.element_from_dict)
        self._event_queue = []
        self._pending = PendingInteractions()
        self._textures = TextureCache()
        self._paint_clock = PaintClock()
        self._widget_state = WidgetState()  # active scene's state (swapped)
        self._screenshot_pending = None
        self._test_auto_click = test_auto_click
        self._start_time = time.time()
        self._current_scene_id = None
        self._imgui_renderer_factory = ImGuiRendererFactory(
            widget_state=self._widget_state,
            texture_cache=self._textures,
            # Display-tier emit is a no-op; interactions route to the Hub.
            emit=lambda _msg: None,
        )

        # Register display-specific query handlers that need ImGui state.
        self._scene_inspector = SceneInspector(
            scenes=self._scenes,
            geometry=self._imgui_renderer_factory.geometry.recorder,
        )
        router = self._query_router
        router.register_handler("inspect_scene", self._scene_inspector.inspect)
        router.register_handler("screenshot", self._query_screenshot)
        router.register_handler("get_display_info", self._query_get_display_info)
        router.register_handler("get_window_settings", self._query_get_window_settings)
        router.register_handler("get_theme", self._query_get_theme)
        frames = FrameCommands(self._scenes)
        router.register_handler("set_frame_state", frames.set_state)
        return self

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def query_router(self) -> QueryRouter:
        """Return the query dispatcher for external handler registration."""
        return self._query_router

    @property
    def scenes(self) -> SceneReplica:
        """Return the scene replica for external inspection."""
        return self._scenes

    @property
    def socket_listener(self) -> SocketListener:
        """Return the socket server for external inspection."""
        return self._socket_listener

    def _drain_stale_events(self, stale_ids: list[str]) -> None:
        """Drop queued and held interactions for removed elements -- both queues."""
        stale = set(stale_ids)
        evicted = self._pending.discard_elements(stale)
        self._event_queue = [
            ev for ev in self._event_queue if ev.element_id not in stale
        ]
        self._interaction_delivery.compensate_evicted(evicted)

    # -- font loading ------------------------------------------------------

    @staticmethod
    def _find_fonts() -> tuple[str | None, list[str]]:
        """Find system fonts for broad Unicode coverage.

        Returns ``(primary, merge_fonts)`` where *primary* is a text font
        with good coverage and *merge_fonts* are symbol fonts merged on
        top to fill gaps (e.g. mathematical angle brackets, Z notation).
        """

        def _first_existing(*candidates: str) -> str | None:
            for p in candidates:
                if Path(p).is_file():
                    return p
            return None

        merge: list[str] = []

        if platform.system() == "Darwin":
            primary = _first_existing(
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            )
            # Apple Symbols fills gaps (math angle brackets U+27E8/E9, etc.)
            sym = _first_existing("/System/Library/Fonts/Apple Symbols.ttf")
            if sym:
                merge.append(sym)
            # STIX Two Math covers Mathematical Alphanumeric Symbols
            # (U+1D400-1D7FF) -- needed for Z notation double-struck letters
            math = _first_existing(
                "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
                "/Library/Fonts/STIXTwoMath.otf",
            )
            if math:
                merge.append(math)
        else:
            # Linux -- DejaVu has good symbol coverage; Noto as fallback
            primary = _first_existing(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            )
            # Noto Sans Symbols for anything DejaVu misses
            sym = _first_existing(
                "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
            )
            if sym:
                merge.append(sym)
            # Noto Sans Math covers Mathematical Alphanumeric Symbols
            # (U+1D400-1D7FF) -- needed for Z notation double-struck letters
            math = _first_existing(
                "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
            )
            if math:
                merge.append(math)

        return primary, merge

    def _load_fonts(self) -> None:
        """hello_imgui ``load_additional_fonts`` callback.

        Loads a system font with Unicode symbol coverage as the default
        font, replacing ImGui's built-in ProggyClean (Latin-only).
        A second symbol font is merged on top to fill remaining gaps
        (Z notation angle brackets, additional mathematical symbols).
        """
        from imgui_bundle import hello_imgui

        primary, merge_fonts = self._find_fonts()
        if primary is None:
            logger.error(
                "No Unicode font found -- using ImGui default (Latin-only). "
                "Unicode symbols will not render correctly."
            )
            return

        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        hello_imgui.load_font(primary, 16.0, params)
        logger.info("Loaded primary font: %s", primary)

        for sym_path in merge_fonts:
            merge_params = hello_imgui.FontLoadingParams()
            merge_params.inside_assets = False
            merge_params.merge_to_last_font = True
            hello_imgui.load_font(sym_path, 16.0, merge_params)
            logger.info("Merged symbol font: %s", sym_path)

    # -- public entry point ------------------------------------------------

    def run(self) -> None:
        """Start the display server (blocking -- ImGui owns the main loop).

        Claims the socket before opening the window: if a live display already
        owns it, this returns immediately so a redundant or racing spawn exits
        cleanly instead of flashing a second window.
        """
        if not self._socket_listener.setup(self._socket_path):
            return
        self._announce_listening()
        # Set process name (visible in ps, top, Activity Monitor)
        try:
            import setproctitle  # pyright: ignore[reportMissingImports]

            setproctitle.setproctitle("luxd-display")
        except ImportError:
            pass

        from imgui_bundle import hello_imgui, immapp

        runner_params = hello_imgui.RunnerParams()
        runner_params.app_window_params.window_title = "Lux"
        runner_params.app_window_params.window_geometry.size = (1200, 800)
        runner_params.imgui_window_params.show_menu_bar = True
        runner_params.imgui_window_params.show_menu_app = False
        runner_params.imgui_window_params.show_menu_view = False
        runner_params.imgui_window_params.show_menu_view_themes = False
        runner_params.imgui_window_params.show_status_bar = False
        runner_params.imgui_window_params.show_status_fps = False
        runner_params.imgui_window_params.remember_status_bar_settings = False
        runner_params.callbacks.load_additional_fonts = self._load_fonts
        runner_params.callbacks.show_menus = self._show_menus
        runner_params.callbacks.post_init = self._on_post_init
        runner_params.callbacks.show_gui = self._on_frame
        runner_params.callbacks.after_swap = self._on_after_swap
        runner_params.callbacks.before_exit = self._on_exit
        runner_params.fps_idling.fps_idle = 30.0
        self._exit_signal = ExitSignal(runner_params)

        addons = immapp.AddOnsParams()
        addons.with_implot = True
        # MarkdownFont points imgui_md at the packaged DejaVu (its own font lacks
        # arrows). Options go once through with_markdown_options (static-guard drop).
        try:
            from imgui_bundle import imgui_md

            md_opts = imgui_md.MarkdownOptions()
            md_opts.font_options.regular_size = 13.0
            MarkdownFont().apply_to(md_opts, hello_imgui.add_assets_search_path)
            addons.with_markdown_options = md_opts
        except ImportError:
            logger.warning("imgui_md unavailable; markdown renders as plain text")
            addons.with_markdown = True

        immapp.run(runner_params, addons)

    def _announce_listening(self) -> None:
        """Record the pid and log once the socket claim has succeeded."""
        self._display_paths.write_pid()
        logger.info("Display server listening on %s", self._socket_path)

    # -- ImGui callbacks ---------------------------------------------------

    def _on_post_init(self) -> None:
        """Called once the OpenGL context is ready."""
        from imgui_bundle import hello_imgui, imgui

        # Ensure docking is enabled (drag-merge frames into tabs).
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable.value

        set_regular_activation_policy()

        # Suppress focus-stealing on every *reshow* after this one (a
        # respawned display's later windows) — GLFW/HelloImGui cannot suppress
        # the one focus grab macOS gives a freshly-created process's first
        # show, a documented limit (display-crash-quarantine.md Question 3),
        # not a defect this call is meant to close.
        self._glfw_window().set_focus_on_show(focus=False)

        self._themes = list(hello_imgui.ImGuiTheme_)

    def _on_frame(self) -> None:
        """Called every frame by ImGui.

        A single bounded send deadline is armed for the whole frame so a burst
        of Acks, Pongs, and query responses under Hub backpressure cannot stack
        per-send waits and wedge the render thread past the ping timeout or the
        macOS "not responding" threshold. Sends past the budget defer, they do
        not block.
        """
        self._socket_listener.set_frame_deadline(time.monotonic() + _FRAME_SEND_BUDGET)
        try:
            self._socket_listener.accept_connections()
            self._socket_listener.poll_clients()
            self._render_scene()
            self._flush_events()
        finally:
            self._socket_listener.clear_frame_deadline()

    def _on_after_swap(self) -> None:
        """Called after GL buffer swap -- GL_FRONT has rendered content."""
        self._paint_clock.swapped()
        if self._screenshot_pending is not None:
            sock = self._screenshot_pending
            self._screenshot_pending = None
            self._capture_screenshot(sock)

    def _capture_screenshot(self, sock: socket.socket) -> None:
        """Capture the OpenGL framebuffer after swap and send the path back.

        Called from ``_on_after_swap`` so GL_FRONT contains the fully
        rendered frame. Uses ``glReadPixels`` with Retina scale factor.
        """
        import os
        import tempfile

        import OpenGL.GL as GL
        from imgui_bundle import hello_imgui, imgui

        try:
            scale = hello_imgui.final_app_window_screenshot_framebuffer_scale()
            io = imgui.get_io()
            fb_width = int(io.display_size.x * scale)
            fb_height = int(io.display_size.y * scale)
            GL.glReadBuffer(GL.GL_FRONT)
            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            data = GL.glReadPixels(
                0, 0, fb_width, fb_height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE
            )

            image = Image.frombytes("RGBA", (fb_width, fb_height), bytes(data))
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

            tmp_dir = Path(tempfile.gettempdir()) / "lux-screenshots"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(
                suffix=".png", prefix="lux-screenshot-", dir=str(tmp_dir)
            )
            os.close(fd)
            image.save(path)

            resp = ScreenshotResponse(path=path)
        except Exception as exc:
            logger.exception("Screenshot capture failed")
            self._query_router.record_error("error", str(exc), "screenshot")
            resp = ScreenshotResponse(error=str(exc))
        self._socket_listener.send_to_client(sock, resp)

    def _on_decorated_toggled(self, decorated: bool) -> None:  # noqa: FBT001
        """Callback for MenuReplica: toggle window decoration."""
        self._decorated = decorated
        self._glfw_window().set_decorated(decorated=decorated)

    def _on_opacity_changed(self, opacity: float) -> None:
        """Callback for MenuReplica: change window opacity."""
        self._opacity = opacity
        self._glfw_window().set_opacity(opacity=opacity)

    def _on_font_scale_changed(self, scale: float) -> None:
        """Callback for MenuReplica: change font scale."""
        self._font_scale = scale

    def _clear_all(self) -> None:
        """Callback for MenuReplica: throw every frame out, then clear scenes and state.

        Clear All means the content is gone, not put away, so every frame is
        disposed whatever visibility the user had left it in.
        """
        for fid in list(self._scenes.frames):
            self._scenes.dispose_frame(fid)
        self._handle_clear()

    def _raise_frame(self, frame_id: str) -> None:
        """Callback for MenuReplica: bring one closed frame back on screen.

        A menu entry has no use for whether the frame was held — it was composed
        from the frames the display holds — so the answer the query surface reads
        is dropped here.
        """
        self._scenes.raise_frame(frame_id)

    def _request_fit_all(self) -> None:
        """Callback for MenuReplica: request fit-all layout."""
        self._fit_all_frames = True

    def _on_exit(self) -> None:
        """Called before the window closes."""
        self._textures.cleanup()
        self._socket_listener.shutdown()
        self._socket_path.unlink(missing_ok=True)
        self._display_paths.remove_pid()
        logger.info("Display server stopped")

    # -- menu bar ----------------------------------------------------------

    def _show_menus(self) -> None:
        self._menus.show_menus()

    def _apply_theme(self, theme_name: str) -> None:
        """Apply a theme by snake_case name (e.g. 'imgui_colors_light')."""
        from imgui_bundle import hello_imgui

        for theme in self._themes:
            if theme.name == theme_name:
                hello_imgui.apply_theme(theme)
                self._current_theme = theme_name
                return
        logger.warning("Unknown theme %r", theme_name)

    @staticmethod
    def _glfw_window() -> GlfwWindow:
        """Return a control handle to the process's live GLFW window."""
        from imgui_bundle import hello_imgui

        address = hello_imgui.get_glfw_window_address()  # type: ignore[attr-defined]
        return GlfwWindow(address)

    # -- socket callbacks ---------------------------------------------------

    def _on_client_disconnected(self, fd: int) -> None:
        """Handle domain-specific cleanup when a client disconnects.

        Called by SocketListener after socket-level state is already cleaned up.
        Transfers ownership of this client's scenes to another client in the same
        frame, or marks them as orphans if no other client remains. Scenes
        persist — they are never dismissed on disconnect.
        """
        self._scenes.reassign_scenes_of(fd, _ORPHAN_FD)

    # -- message handling --------------------------------------------------

    def _handle_message(self, sock: socket.socket, msg: Message) -> None:
        """Dispatch a scene/menu/theme-mutating message; read-only kinds delegate."""
        if isinstance(msg, SceneMessage):
            self._handle_scene(sock, msg)
        elif isinstance(msg, MenuMessage):
            self._menus.replace_agent_menus(msg.menus)
        elif isinstance(msg, CallbackMenuMessage):
            self._menus.replace_callback_menus(msg.submenus)
        elif isinstance(msg, ThemeMessage):
            self._apply_theme(msg.theme)
        elif isinstance(msg, ConnectMessage):
            self._handle_connect(sock, msg)
        elif isinstance(msg, HubManifestMessage):
            self._handle_hub_manifest(sock, msg)
        else:
            self._handle_readonly_message(sock, msg)

    def _handle_clear(self) -> None:
        """Drop all scenes and reset per-frame state — the World-menu 'clear all'."""
        self._interaction_delivery.compensate_evicted(self._pending.evict_all())
        self._scenes.clear_all()
        self._event_queue.clear()
        self._widget_state = WidgetState()

    def _handle_readonly_message(self, sock: socket.socket, msg: Message) -> None:
        """Dispatch a read-only introspect/query/ping message; unknown kinds ignored."""
        if isinstance(msg, PingMessage):
            pong = PongMessage(ts=msg.ts, display_ts=time.time())
            self._socket_listener.send_to_client(sock, pong)
        elif isinstance(msg, IntrospectRequest):
            self._handle_introspect(sock, msg)
        elif isinstance(msg, ListScenesRequest):
            self._handle_list_scenes(sock, msg)
        elif isinstance(msg, ScreenshotRequest):
            self._screenshot_pending = sock
        elif isinstance(msg, QueryRequest):
            self._handle_query(sock, msg)
        elif isinstance(msg, UnknownMessage):
            logger.debug("Ignoring unknown message type %r", msg.raw_type)

    def _handle_connect(self, sock: socket.socket, msg: ConnectMessage) -> None:
        """Record a client's declared identity; preempt a stale Hub (DES-068)."""
        self._hub_reconciliation.handle_connect(sock, msg)

    def _handle_hub_manifest(
        self, sock: socket.socket, msg: HubManifestMessage
    ) -> None:
        """Purge every scene a Hub manifest disowns (DES-068)."""
        self._hub_reconciliation.handle_manifest(sock, msg)

    def _handle_introspect(self, sock: socket.socket, msg: IntrospectRequest) -> None:
        """Return the element tree for a scene to the requesting client."""
        qr = self._query_router.handle_query(
            "inspect_scene", {"scene_id": msg.scene_id}
        )
        if qr.error is not None:
            resp = IntrospectResponse(
                scene_id=msg.scene_id,
                error=qr.error,
            )
        else:
            resp = IntrospectResponse(
                scene_id=msg.scene_id,
                elements=qr.result["elements"],
            )
        self._socket_listener.send_to_client(sock, resp)

    def _handle_list_scenes(self, sock: socket.socket, _msg: ListScenesRequest) -> None:
        """Return the list of active scenes and frames."""
        qr = self._query_router.handle_query("list_scenes", None)
        if qr.error is not None:
            resp = ListScenesResponse(scenes=[], frames=[])
        else:
            resp = ListScenesResponse(
                scenes=qr.result["scenes"], frames=qr.result["frames"]
            )
        self._socket_listener.send_to_client(sock, resp)

    # -- generic query dispatcher ------------------------------------------

    def _handle_query(self, sock: socket.socket, msg: QueryRequest) -> None:
        """Dispatch a generic QueryRequest to the registered handler."""
        resp = self._query_router.handle_query(msg.method, msg.params)
        self._socket_listener.send_to_client(sock, resp)

    def _query_screenshot(self, **_kwargs: Any) -> dict[str, Any]:
        """Query handler for screenshot.

        Screenshots require GL context (post-swap capture).  The generic
        query path cannot defer to the frame loop.
        """
        msg = "Use the dedicated screenshot_request message"
        raise RuntimeError(msg)

    def _query_get_display_info(self, **_kwargs: Any) -> dict[str, Any]:
        """Return display server metadata."""
        import os

        from imgui_bundle import hello_imgui

        backend = str(hello_imgui.get_runner_params().renderer_backend_type)
        screen_size = (
            hello_imgui.get_runner_params().app_window_params.window_geometry.size
        )

        return {
            "backend": backend,
            "window_width": screen_size[0],
            "window_height": screen_size[1],
            "fps": round(hello_imgui.frame_rate(), 1),
            "pid": os.getpid(),
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "protocol_version": "1.0",
            "element_kinds": len(DEFAULT_ABC_REGISTRY.all_kinds),
        }

    def _query_get_window_settings(self, **_kwargs: Any) -> dict[str, Any]:
        """Return opacity, the stored 0.5-3.0 font scale, decoration, and idle rate."""
        from imgui_bundle import hello_imgui

        return {
            "opacity": self._opacity,
            "font_scale": self._font_scale,
            "decorated": self._decorated,
            "fps_idle": hello_imgui.get_runner_params().fps_idling.fps_idle,
        }

    def _query_get_theme(self, **_kwargs: Any) -> dict[str, Any]:
        """Return the current theme and the switchable themes as bare names."""
        return {
            "current": self._current_theme,
            "available": [t.name for t in self._themes if t.name != "count"],
        }

    @trace
    def _emit_event(self, event: RemoteEventHandlerInvocation) -> None:
        """Stamp scene_id and queue for delivery to the Hub.

        D21: the display dispatches no interactions locally. The
        ``remote_dispatch`` handler on each element sends the
        ``RemoteEventHandlerInvocation`` to the Hub, where the real handler
        fires. This method is the socket-send path the ``remote_dispatch``
        closure captures.
        """
        if event.scene_id is None:
            event = dataclasses.replace(event, scene_id=self._current_scene_id)
        logger.debug(
            "_emit_event queued element_id=%s action=%s scene_id=%s",
            event.element_id,
            event.action,
            event.scene_id,
        )
        self._event_queue.append(event)

    def client_name(self, fd: int) -> str | None:
        """Return the display name for a connected client, or ``None``."""
        return self._socket_listener.client_names.get(fd)

    def _handle_scene(self, sock: socket.socket, msg: SceneMessage) -> None:
        """Route a scene into its frame, creating the frame if needed.

        Every scene carries a frame — the Hub synthesizes one at the render
        boundary when the caller names none (frame_id = scene_id), so the display
        has a single, always-framed install path.
        """
        try:
            fd = sock.fileno()
        except OSError:
            return
        if self._hub_reconciliation.reject_scene_if_test_kind(sock, fd):
            return
        self._paint_clock.received(msg.id)
        self._wrap_abc_elements(msg)
        self._scenes.handle_framed_scene(msg, fd)
        ack = AckMessage(scene_id=msg.id, ts=time.time())
        self._socket_listener.send_to_client(sock, ack)
        if self._test_auto_click:
            self._auto_click_buttons(msg)

    def _wrap_abc_elements(self, msg: SceneMessage) -> None:
        """Rebind the real factory and wrap handlers on received elements.

        Each top-level element and its ``_children()`` subtree get the Display's
        ``ImGuiRendererFactory`` and ``remote_dispatch`` handler wrapping.
        """
        for elem in msg.elements:
            elem.bind_renderer_factory(self._imgui_renderer_factory)
            elem.wrap_handlers_for_remote(self._emit_event)

    def _auto_click_buttons(self, msg: SceneMessage) -> None:
        """Enqueue synthetic interactions for testable elements (test mode).

        Synthetic events run BEFORE the first render loop assigns
        ``self._current_scene_id`` from ``_render_framed_scene``.
        Without stamping the scene id here, ``_emit_event`` would queue the
        event with ``scene_id=None`` and the Hub could never resolve which
        scene the synthetic click belongs to. Save / restore the prior value
        so the render loop's later assignment is undisturbed.
        """
        prior_scene_id = self._current_scene_id
        self._current_scene_id = msg.id
        try:
            AutoClicker(self._emit_event).click_all(msg)
        finally:
            self._current_scene_id = prior_scene_id

    # -- rendering ---------------------------------------------------------

    def _render_scene(self) -> None:
        from imgui_bundle import imgui

        imgui.get_style().font_scale_main = self._font_scale

        # Provide a viewport-wide dock space so manual imgui.begin() windows
        # can be dragged into tabbed dock nodes by the user.
        imgui.dock_space_over_viewport(
            flags=imgui.DockNodeFlags_.passthru_central_node.value,
        )

        # Always render the ambient flame as a background element.
        # Content renders on top of it.
        render_idle(imgui)

        # World menu: background click to toggle, floating panel.
        self._menus.check_world_menu_background_click(imgui)
        self._menus.render_world_panel(imgui)

        # Every scene renders inside a frame (workspace model); there is no
        # unframed scene surface — the Hub frames every scene at the boundary.
        self._render_frames(imgui)

        # Promote this frame's rects into the snapshot the next frame's query
        # reads (that query runs in poll_clients before the next render).
        self._imgui_renderer_factory.geometry.complete()

    # Cascade layout: each new frame offsets from the previous one.
    _CASCADE_BASE_X = 30.0
    _CASCADE_BASE_Y = 40.0
    _CASCADE_DX = 30.0
    _CASCADE_DY = 30.0
    _FRAME_FILL = 0.75

    _FLAG_MAP: ClassVar[dict[str, str]] = {
        "no_resize": "no_resize",
        "no_collapse": "no_collapse",
        "auto_resize": "always_auto_resize",
        "no_title_bar": "no_title_bar",
        "no_background": "no_background",
        "no_scrollbar": "no_scrollbar",
    }

    def _resolve_frame_flags(self, frame: Frame, imgui: Any) -> int:
        """Map frame flag names to an ImGui window flags bitmask."""
        result = 0
        if not frame.flags:
            return result
        for key, enabled in frame.flags.items():
            if not enabled:
                continue
            attr = self._FLAG_MAP.get(key)
            if attr is None:
                continue
            flag = getattr(imgui.WindowFlags_, attr, None)
            if flag is not None:
                result |= flag.value
        return result

    def _apply_fit_all(self) -> bool:
        """If fit-all was requested, undock every frame and compute tile layout.

        Returns True when fitting is active (callers should use
        ``Cond_.always`` for position/size).

        A *closed* frame is left closed. Fitting is a layout command over the
        frames the user has on screen; pulling back a window they deliberately
        shut would be a raise wearing a tiling command's clothes. Expand All and
        the Windows menu's closed list are the gestures that mean "bring it back".
        """
        if not self._fit_all_frames:
            return False
        self._fit_all_frames = False
        for frame in self._scenes.docked_frames():
            frame.restore()
        return True

    def _cascaded_frame_size(
        self, frame: Frame, default_size: tuple[float, float]
    ) -> tuple[float, float]:
        """Return the frame's own initial size, or ``default_size`` if unset."""
        if not frame.initial_size:
            return default_size
        return float(frame.initial_size[0]), float(frame.initial_size[1])

    def _render_single_frame(
        self, frame: Frame, imgui: Any, placement: FramePlacement
    ) -> tuple[str | None, bool]:
        """Render one frame window.

        Returns (result, hovered) where result is 'closed', 'minimized',
        or None, and hovered indicates the mouse is over this frame.
        """
        # A fit-all pass places this frame at its computed tile rect, if one
        # was assigned; falling through covers both "not fitting" and "fitting
        # but this frame has no tile yet" in one branch.
        tiled = placement.tile_layout.get(frame.frame_id) if placement.fitting else None
        if tiled is not None:
            cond = imgui.Cond_.always.value
            x, y, fw, fh = tiled
        else:
            cond = imgui.Cond_.first_use_ever.value
            x = self._CASCADE_BASE_X + frame.cascade_index * self._CASCADE_DX
            y = self._CASCADE_BASE_Y + frame.cascade_index * self._CASCADE_DY
            fw, fh = self._cascaded_frame_size(frame, placement.default_size)
        imgui.set_next_window_pos((x, y), cond)
        imgui.set_next_window_size((fw, fh), cond)
        if self._scenes.consume_focus(frame.frame_id):
            imgui.set_next_window_focus()
            logger.info("raise frame=%s applied", frame.frame_id)
        win_flags = self._resolve_frame_flags(frame, imgui)
        still_open = True
        expanded, still_open = imgui.begin(
            f"{frame.title}##{frame.frame_id}", still_open, win_flags
        )
        hovered = imgui.is_window_hovered(
            imgui.HoveredFlags_.root_and_child_windows.value
        )
        if not still_open:
            imgui.end()
            return "closed", hovered
        if not expanded:
            # Collapse triangle clicked -- minimize to the dock bar, unless docked
            # (ImGui transiently reports expanded=False mid-docking transition; a
            # docked-collapsed frame still paints its tab, so it records below).
            if not imgui.is_window_docked():
                imgui.set_window_collapsed(False)
                imgui.end()
                return "minimized", hovered
        else:
            self._render_frame_contents(frame, imgui)
        # Record the painted rect after contents lay out, so an auto-resized frame
        # captures its final size, not a stale one. Display-local, never Hub state.
        self._imgui_renderer_factory.geometry.record_frame(frame.frame_id)
        imgui.end()
        return None, hovered

    def _render_frames(self, imgui: Any) -> None:
        """Render each frame as an ImGui inner window."""
        # Default frame size: 75% of content region (first use only).
        region = imgui.get_content_region_avail()
        frame_w = max(400.0, region.x * self._FRAME_FILL)
        frame_h = max(300.0, region.y * self._FRAME_FILL)

        sm = self._scenes
        fitting = self._apply_fit_all()
        on_screen = sm.on_screen_frames()
        tile_layout: dict[str, tuple[float, float, float, float]] = {}
        if fitting:
            tile_layout = FrameTiling(on_screen).cells(imgui, region)
        placement = FramePlacement(
            fitting=fitting, tile_layout=tile_layout, default_size=(frame_w, frame_h)
        )

        closed_frames: list[str] = []
        minimized_frames: list[str] = []
        any_frame_hovered = False
        for frame in on_screen:
            result, hovered = self._render_single_frame(frame, imgui, placement)
            any_frame_hovered = any_frame_hovered or hovered
            if result == "closed":
                closed_frames.append(frame.frame_id)
            elif result == "minimized":
                minimized_frames.append(frame.frame_id)
        for fid in closed_frames:
            self._close_frame(fid)
        for fid in minimized_frames:
            sm.minimize(fid)
        # Dock bar for docked frames — a closed frame carries no pill.
        DockBar(imgui, self._scenes).render(any_frame_hovered=any_frame_hovered)

    def _render_frame_contents(self, frame: Frame, imgui: Any) -> None:
        """Render scenes inside a frame.

        Layout modes:
        - ``"tab"`` (default): multiple scenes as tabs, one visible at a time.
        - ``"stack"``: all scenes stacked vertically with collapsing headers.
        """
        if not frame.scenes:
            return
        if len(frame.scenes) == 1:
            scene_id = frame.scene_order[0]
            self._render_framed_scene(frame, scene_id)
            return
        if frame.layout == "stack":
            self._render_frame_stack(frame, imgui)
        else:
            self._render_frame_tabs(frame, imgui)

    def _render_frame_tabs(self, frame: Frame, imgui: Any) -> None:
        """Render multi-scene frame as tabs."""
        if imgui.begin_tab_bar(f"##frame_tabs_{frame.frame_id}"):
            closed_tabs: list[str] = []
            for scene_id in list(frame.scene_order):
                scene = frame.scenes[scene_id]
                label = scene.title or scene_id
                closable = True
                selected, tab_open = imgui.begin_tab_item(
                    f"{label}##{scene_id}", closable
                )
                if selected:
                    frame.active_tab = scene_id
                    self._render_framed_scene(frame, scene_id)
                    imgui.end_tab_item()
                if tab_open is not None and not tab_open:
                    closed_tabs.append(scene_id)
            imgui.end_tab_bar()
            for sid in closed_tabs:
                frame_empty = self._scenes.dismiss_framed_scene(frame, sid)
                if frame_empty:
                    self._scenes.dispose_frame(frame.frame_id)

    def _render_frame_stack(self, frame: Frame, imgui: Any) -> None:
        """Render multi-scene frame as vertically stacked collapsing headers.

        Unlike tab layout, stack layout has no per-scene close affordance.
        Scenes represent live data feeds (e.g. per-repo status) and are
        managed programmatically, not dismissed by the user.
        """
        for scene_id in list(frame.scene_order):
            scene = frame.scenes[scene_id]
            label = scene.title or scene_id
            flags = imgui.TreeNodeFlags_.default_open.value
            if imgui.collapsing_header(f"{label}##{scene_id}", flags=flags):
                imgui.push_id(scene_id)
                self._render_framed_scene(frame, scene_id)
                imgui.pop_id()

    def _render_framed_scene(self, frame: Frame, scene_id: str) -> None:
        """Render a scene's elements inside a frame."""
        ws = self._scenes.widget_state_for(scene_id)
        if ws is not None:
            self._widget_state = ws
            self._imgui_renderer_factory.widget_state = ws
        # ``_emit_event`` stamps scene_id from ``self._current_scene_id``
        # for any RemoteEventHandlerInvocation whose scene_id is None —
        # without this assignment, clicks inside framed scenes would carry
        # whatever a prior frame's render last set (stale or None), and the
        # Hub could never resolve which scene the click belongs to.
        self._current_scene_id = scene_id
        self._paint_clock.painted(scene_id)
        self._imgui_renderer_factory.geometry.enter_scene(scene_id)
        scene = frame.scenes[scene_id]
        # Every kind is an Element-ABC subclass, so painting is one render() call.
        for elem in scene.elements:
            elem.render()

    def _close_frame(self, frame_id: str) -> None:
        """Put a frame away: the user clicked its ✕.

        Closing is the Display's own decision about where a window is, and it
        tells the owning clients nothing. The frame keeps its scenes, its widget
        state and its tab, so raising it later brings back what the user shut
        rather than a blank rebuilt from the next push.

        The one thing it does beyond the visibility write is drop this Display's
        queued interactions that originated in the frame's scenes, so a button in
        a window the user just shut cannot fire afterwards. That drain reaches no
        one outside this process, and it is scoped by scene rather than by
        element id: ids are shareable across scenes, so draining by id would
        cancel a click the user is still waiting on in a frame that is up.
        """
        self._drop_queued_interactions(self._scenes.close(frame_id))

    def _drop_queued_interactions(self, scene_ids: list[str]) -> None:
        """Drop queued and held interactions that came from ``scene_ids``.

        The scene-scoped counterpart to :meth:`_drain_stale_events`. That one
        answers "these elements are gone"; this one answers "this frame is not
        on screen any more", and the two need different scopings because an
        element id can be held by more than one scene at once.
        """
        scenes = set(scene_ids)
        evicted = self._pending.discard_scenes(scenes)
        self._event_queue = [
            ev for ev in self._event_queue if ev.scene_id not in scenes
        ]
        self._interaction_delivery.compensate_evicted(evicted)

    # -- event flushing ----------------------------------------------------

    def _record_queued_events(self) -> None:
        """Copy queued events into the introspection ring buffer."""
        for event in self._event_queue:
            self._query_router.record_event(
                {
                    "element_id": event.element_id,
                    "action": event.action,
                    "event_kind": event.event_kind,
                    "value": event.value,
                    "timestamp": event.ts if event.ts is not None else time.time(),
                }
            )

    def _flush_events(self) -> None:
        """Deliver queued interactions within one frame budget; hold the rest.

        New join the buffer; aged expire and compensate; the unsent remainder holds.
        """
        if not self._event_queue and self._pending.is_empty:
            return
        self._record_queued_events()
        now = time.monotonic()
        self._pending.admit(self._event_queue, now)
        self._event_queue.clear()
        expired = self._pending.expire(now)
        if self._socket_listener.clients:
            self._pending.discard_prefix(
                self._interaction_delivery.deliver(self._pending.pending_events())
            )
        self._interaction_delivery.compensate_evicted(expired)
