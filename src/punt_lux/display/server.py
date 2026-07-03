# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Lux display server — ImGui render loop with non-blocking Unix socket IPC.

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

from punt_lux.display.domain_pump import DomainPump
from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.idle_screen import render_idle
from punt_lux.display.macos import hide_from_dock_and_cmd_tab
from punt_lux.display.menu_manager import MenuManager
from punt_lux.display.renderers.imgui import ImGuiRendererFactory
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.domain.display import Display
from punt_lux.domain.ids import ClientId
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    CheckboxElement,
    ClearMessage,
    ColorPickerElement,
    ComboElement,
    ConnectMessage,
    InputNumberElement,
    InputTextElement,
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    MenuMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    RadioElement,
    RegisterMenuMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    ScreenshotRequest,
    ScreenshotResponse,
    SelectableElement,
    SliderElement,
    ThemeMessage,
    UnknownMessage,
    UpdateMessage,
)
from punt_lux.protocol.elements import Element
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.query_dispatcher import QueryDispatcher
from punt_lux.scene import Frame, SceneManager, WidgetState
from punt_lux.socket_server import SocketServer
from punt_lux.tracing import trace

# Element kinds with a per-class renderer in ``display.renderers``.
# Scenes containing only these kinds route through ``Display.apply``
# alongside SceneManager.  Mixed scenes (containing any other kind)
# still go exclusively through SceneManager until subsequent PRs
# migrate the remaining families.
_BASICS_KINDS: tuple[type, ...] = (
    TextElement,
    ImageElement,
    SeparatorElement,
    ProgressElement,
    SpinnerElement,
    MarkdownElement,
)
_INPUTS_KINDS: tuple[type, ...] = (
    ButtonElement,
    SliderElement,
    CheckboxElement,
    ComboElement,
    InputTextElement,
    InputNumberElement,
    RadioElement,
    ColorPickerElement,
    SelectableElement,
)
# Composite kinds. The pump's _install_subtree recursively installs each
# child; the top-level composite must appear in _NATIVE_KINDS so route()'s
# mixed-scene gate admits the scene.
_COMPOSITE_KINDS: tuple[type, ...] = (DialogElement,)
_NATIVE_KINDS: tuple[type, ...] = _BASICS_KINDS + _INPUTS_KINDS + _COMPOSITE_KINDS

if TYPE_CHECKING:
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

# Sentinel fd for scenes whose owning client has disconnected and no other
# client remains in the frame.  The scene persists until the user closes the
# frame or a new client adopts it.
_ORPHAN_FD = -1


class DisplayServer:
    """ImGui display server with non-blocking Unix socket IPC."""

    _socket_path: Path
    _socket_server: SocketServer
    _scene_manager: SceneManager
    _domain_display: Display
    _domain_client_id: ClientId
    _domain_pump: DomainPump
    _event_queue: list[RemoteEventHandlerInvocation]
    _textures: TextureCache
    _table_renderer: TableRenderer
    _widget_state: WidgetState
    _menu_manager: MenuManager
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
    _query_dispatcher: QueryDispatcher
    _display_paths: DisplayPaths
    _element_renderer: ElementRenderer
    _imgui_renderer_factory: ImGuiRendererFactory
    _luxd_factory: Any  # JsonElementFactory, declared Any to avoid an import cycle

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
        self._scene_manager = SceneManager(
            on_scene_replaced=self._drain_stale_events,
        )
        # Parallel domain Display (PR 1): basics-only scenes are also
        # routed through Display.apply so the new infrastructure has a
        # real production caller (PY-RF-2).  Renderer reads from
        # SceneManager during PR 1+2; later PRs route rendering through
        # Display.snapshot.  ``_domain_client_id`` is the synthetic
        # client that owns every wire-decoded element on this hub.
        self._domain_display = Display()
        self._domain_client_id = self._domain_display.connect_client(name="display-hub")
        self._domain_pump = DomainPump(
            self._domain_display,
            self._domain_client_id,
            _NATIVE_KINDS,
        )
        self._themes = []
        self._decorated = True
        self._opacity = 1.0
        self._font_scale = 1.1
        self._fit_all_frames = False
        self._current_theme = "imgui_colors_dark"
        # MenuManager must be created before QueryDispatcher so that
        # its properties are available for the lambda callbacks.
        self._menu_manager = MenuManager(
            emit_event=self._emit_event,
            on_theme_selected=self._apply_theme,
            on_decorated_toggled=self._on_decorated_toggled,
            on_opacity_changed=self._on_opacity_changed,
            on_font_scale_changed=self._on_font_scale_changed,
            get_themes=lambda: self._themes,
            get_decorated=lambda: self._decorated,
            get_opacity=lambda: self._opacity,
            get_font_scale=lambda: self._font_scale,
            get_frames=lambda: self._scene_manager.frames,
            get_client_names=lambda: self._socket_server.client_names,
            on_clear_all=self._clear_all,
            on_fit_all=self._request_fit_all,
        )
        # QueryDispatcher must be created before SocketServer so that
        # the on_error callback is available.
        self._query_dispatcher = QueryDispatcher(
            scene_manager=self._scene_manager,
            get_client_names=lambda: self._socket_server.client_names,
            get_client_connect_times=lambda: self._socket_server.client_connect_times,
            get_menu_registrations=lambda: self._menu_manager.menu_registrations,
            get_agent_menus=lambda: self._menu_manager.agent_menus,
        )
        self._socket_server = SocketServer(
            on_message=self._handle_message,
            on_client_disconnected=self._on_client_disconnected,
            on_error=self._query_dispatcher.record_error,
        )
        # Install the luxd-tier element factory so inbound scene
        # decoding (via reader.drain_typed → _scene_from_dict →
        # layout._from_dict_dispatch) routes through a real factory.
        # The Display is not allowed to own business publish behavior;
        # if a handler ever runs locally before remote wrapping, that
        # path must fail loudly instead of silently dropping the publish.
        from punt_lux.display_client import no_op_emit
        from punt_lux.protocol.element_factory import JsonElementFactory
        from punt_lux.protocol.elements import (
            build_element_codec,
            layout as _element_layout,
        )
        from punt_lux.protocol.raising_publish_sink import RaisingPublishSink

        self._luxd_factory = JsonElementFactory(
            renderer_factory=RaisingRendererFactory(),
            emit=no_op_emit,
            publish_sink=cast(
                "Any",
                RaisingPublishSink("DisplayServer._luxd_factory"),
            ),
            codec=build_element_codec(),
        )
        _element_layout.install_from_dict(self._luxd_factory.element_from_dict)
        self._event_queue = []
        self._textures = TextureCache()
        self._widget_state = WidgetState()  # active scene's state (swapped)
        self._table_renderer = TableRenderer(
            widget_state=self._widget_state,
            emit_event=self._emit_event,
        )
        self._screenshot_pending = None
        self._test_auto_click = test_auto_click
        self._start_time = time.time()
        self._current_scene_id = None
        self._element_renderer = ElementRenderer(
            widget_state=self._widget_state,
            texture_cache=self._textures,
            table_renderer=self._table_renderer,
            emit_event=self._emit_event,
            check_dirty_window=self._check_dirty_window,
        )
        self._imgui_renderer_factory = ImGuiRendererFactory(
            widget_state=self._widget_state,
            texture_cache=self._textures,
            # Display-tier emit is a no-op; interactions route to the Hub.
            emit=lambda _msg: None,
            # ImGuiTextRenderer delegates back to ElementRenderer so the
            # generic post-processing (styled-text tooltip hover) keeps
            # working through the per-kind renderer dispatch path.
            element_renderer=self._element_renderer,
        )

        # Register display-specific query handlers that need ImGui state.
        qd = self._query_dispatcher
        qd.register_handler("screenshot", self._query_screenshot)
        qd.register_handler("get_display_info", self._query_get_display_info)
        qd.register_handler("get_window_settings", self._query_get_window_settings)
        qd.register_handler("get_theme", self._query_get_theme)
        qd.register_handler("set_window_settings", self._query_set_window_settings)
        qd.register_handler("set_frame_state", self._query_set_frame_state)
        qd.register_handler("set_theme", self._query_set_theme)
        return self

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def query_dispatcher(self) -> QueryDispatcher:
        """Return the query dispatcher for external handler registration."""
        return self._query_dispatcher

    @property
    def scene_manager(self) -> SceneManager:
        """Return the scene manager for external inspection."""
        return self._scene_manager

    @property
    def socket_server(self) -> SocketServer:
        """Return the socket server for external inspection."""
        return self._socket_server

    def _drain_stale_events(self, stale_ids: list[str]) -> None:
        """Remove queued events for elements that no longer exist."""
        stale = set(stale_ids)
        self._event_queue = [
            ev for ev in self._event_queue if ev.element_id not in stale
        ]

    def _check_dirty_window(self, window_id: str) -> bool:
        """Check and clear the dirty flag for a window element."""
        dw = self._scene_manager.dirty_windows
        if window_id in dw:
            dw.discard(window_id)
            return True
        return False

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
        """Start the display server (blocking -- ImGui owns the main loop)."""
        # Set process name (visible in ps, top, Activity Monitor)
        try:
            import setproctitle  # pyright: ignore[reportMissingImports]

            setproctitle.setproctitle("Lux")
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

        addons = immapp.AddOnsParams()
        addons.with_implot = True
        # Set markdown regular_size to match the system font visually.
        # imgui_md loads Roboto (bundled) which renders larger than system
        # fonts at the same nominal px.  Do NOT also set with_markdown=True
        # -- InitializeMarkdown has a static guard that silently drops the
        # second call, so the custom options would be ignored.
        try:
            from imgui_bundle import imgui_md

            md_opts = imgui_md.MarkdownOptions()
            md_opts.font_options.regular_size = 13.0
            addons.with_markdown_options = md_opts
        except ImportError:
            addons.with_markdown = True

        immapp.run(runner_params, addons)

    # -- ImGui callbacks ---------------------------------------------------

    def _on_post_init(self) -> None:
        """Called once the OpenGL context is ready."""
        import signal

        from imgui_bundle import hello_imgui, imgui

        # Ensure docking is enabled (drag-merge frames into tabs).
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable.value

        hide_from_dock_and_cmd_tab()

        self._themes = list(hello_imgui.ImGuiTheme_)
        self._socket_server.setup(self._socket_path)
        self._display_paths.write_pid()

        signal.signal(signal.SIGTERM, self._handle_sigterm)

        logger.info("Display server listening on %s", self._socket_path)

    def _on_frame(self) -> None:
        """Called every frame by ImGui."""
        self._socket_server.accept_connections()
        self._socket_server.poll_clients()
        self._render_scene()
        self._flush_events()

    def _on_after_swap(self) -> None:
        """Called after GL buffer swap -- GL_FRONT has rendered content."""
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
            self._query_dispatcher.record_error("error", str(exc), "screenshot")
            resp = ScreenshotResponse(error=str(exc))
        self._socket_server.send_to_client(sock, resp)

    def _on_decorated_toggled(self, decorated: bool) -> None:  # noqa: FBT001
        """Callback for MenuManager: toggle window decoration."""
        self._decorated = decorated
        self._set_glfw_decorated(decorated=decorated)

    def _on_opacity_changed(self, opacity: float) -> None:
        """Callback for MenuManager: change window opacity."""
        self._opacity = opacity
        self._set_glfw_opacity(opacity=opacity)

    def _on_font_scale_changed(self, scale: float) -> None:
        """Callback for MenuManager: change font scale."""
        self._font_scale = scale

    def _clear_all(self) -> None:
        """Callback for MenuManager: clear all frames and scenes."""
        for fid in list(self._scene_manager.frames):
            self._close_frame(fid)
        self._scene_manager.clear_all()
        self._event_queue.clear()
        self._widget_state = WidgetState()

    def _request_fit_all(self) -> None:
        """Callback for MenuManager: request fit-all layout."""
        self._fit_all_frames = True

    def _handle_sigterm(self, _signum: int, _frame: object) -> None:
        """SIGTERM handler — remove PID file and exit."""
        self._display_paths.remove_pid()
        raise SystemExit(0)

    def _on_exit(self) -> None:
        """Called before the window closes."""
        self._textures.cleanup()
        self._socket_server.shutdown()
        self._menu_manager.clear_menus()
        self._socket_path.unlink(missing_ok=True)
        self._display_paths.remove_pid()
        logger.info("Display server stopped")

    # -- menu bar ----------------------------------------------------------

    def _show_menus(self) -> None:
        self._menu_manager.show_menus()

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
    def _set_glfw_decorated(*, decorated: bool) -> None:
        """Toggle window decoration at runtime via GLFW.

        Uses RTLD_NOLOAD to grab the already-loaded libglfw handle
        rather than loading a second copy (which triggers duplicate
        Objective-C class warnings on macOS).
        """
        import ctypes

        from imgui_bundle import hello_imgui

        glfw_decorated = 0x00020005  # GLFW_DECORATED
        window_addr = hello_imgui.get_glfw_window_address()  # type: ignore[attr-defined]

        # RTLD_NOLOAD (0x10 on macOS) returns the existing handle
        # without loading a second copy of the library.
        rtld_noload = 0x10
        glfw_lib = ctypes.CDLL("libglfw.3.dylib", mode=rtld_noload)
        glfw_lib.glfwSetWindowAttrib.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        glfw_lib.glfwSetWindowAttrib(
            ctypes.c_void_p(window_addr),
            glfw_decorated,
            int(decorated),
        )

    @staticmethod
    def _set_glfw_opacity(*, opacity: float) -> None:
        """Set window opacity at runtime via GLFW."""
        import ctypes

        from imgui_bundle import hello_imgui

        window_addr = hello_imgui.get_glfw_window_address()  # type: ignore[attr-defined]
        rtld_noload = 0x10
        glfw_lib = ctypes.CDLL("libglfw.3.dylib", mode=rtld_noload)
        glfw_lib.glfwSetWindowOpacity.argtypes = [ctypes.c_void_p, ctypes.c_float]
        glfw_lib.glfwSetWindowOpacity(ctypes.c_void_p(window_addr), opacity)

    # -- socket callbacks ---------------------------------------------------

    def _on_client_disconnected(self, fd: int) -> None:
        """Handle domain-specific cleanup when a client disconnects.

        Called by SocketServer after socket-level state is already cleaned up.
        Handles menu registration cleanup and scene ownership transfer.
        """
        self._menu_manager.on_client_disconnected(fd)
        # Transfer ownership of this client's scenes to another client
        # in the same frame, or mark them as orphans if no other client
        # remains.  Scenes persist -- they are never dismissed on disconnect.
        sm = self._scene_manager
        for f in list(sm.frames.values()):
            f.owner_fds.discard(fd)
            owned_scenes = [
                sid for sid in f.scene_order if sm.scene_to_owner.get(sid) == fd
            ]
            for sid in owned_scenes:
                remaining = f.owner_fds
                if remaining:
                    sm.scene_to_owner[sid] = next(iter(remaining))
                else:
                    sm.scene_to_owner[sid] = _ORPHAN_FD

    # -- message handling --------------------------------------------------

    def _handle_message(self, sock: socket.socket, msg: Message) -> None:  # noqa: C901
        if isinstance(msg, SceneMessage):
            self._handle_scene(sock, msg)
        elif isinstance(msg, UpdateMessage):
            self._scene_manager.apply_update(msg)
            self._socket_server.send_to_client(
                sock,
                AckMessage(scene_id=msg.scene_id, ts=time.time()),
            )
        elif isinstance(msg, ClearMessage):
            self._scene_manager.clear_all()
            self._event_queue.clear()
            self._widget_state = WidgetState()
        elif isinstance(msg, RegisterMenuMessage):
            self._handle_register_menu(sock, msg)
        elif isinstance(msg, MenuMessage):
            self._menu_manager.agent_menus = msg.menus
        elif isinstance(msg, ThemeMessage):
            self._apply_theme(msg.theme)
        elif isinstance(msg, ConnectMessage):
            self._handle_connect(sock, msg)
        elif isinstance(msg, PingMessage):
            pong = PongMessage(ts=msg.ts, display_ts=time.time())
            self._socket_server.send_to_client(sock, pong)
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
        """Record a client's display name (idempotent)."""
        name = msg.name.strip()
        if not name:
            logger.warning("ConnectMessage with empty name -- ignored")
            return
        try:
            fd = sock.fileno()
        except OSError:
            return
        self._socket_server.register_client_name(fd, name, time.time())
        logger.info("Client fd=%d identified as %r", fd, name)

    def _handle_introspect(self, sock: socket.socket, msg: IntrospectRequest) -> None:
        """Return the element tree for a scene to the requesting client."""
        qr = self._query_dispatcher.handle_query(
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
        self._socket_server.send_to_client(sock, resp)

    def _handle_list_scenes(self, sock: socket.socket, _msg: ListScenesRequest) -> None:
        """Return the list of active scenes and frames."""
        qr = self._query_dispatcher.handle_query("list_scenes", None)
        if qr.error is not None:
            resp = ListScenesResponse(scenes=[], frames=[])
        else:
            resp = ListScenesResponse(
                scenes=qr.result["scenes"], frames=qr.result["frames"]
            )
        self._socket_server.send_to_client(sock, resp)

    # -- generic query dispatcher ------------------------------------------

    def _handle_query(self, sock: socket.socket, msg: QueryRequest) -> None:
        """Dispatch a generic QueryRequest to the registered handler."""
        resp = self._query_dispatcher.handle_query(msg.method, msg.params)
        self._socket_server.send_to_client(sock, resp)

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
            "element_kinds": self._element_renderer.element_kind_count,
        }

    def _query_get_window_settings(self, **_kwargs: Any) -> dict[str, Any]:
        """Return current window settings."""
        from imgui_bundle import hello_imgui, imgui

        return {
            "font_scale": round(imgui.get_font_size(), 1),
            "fps_idle": hello_imgui.get_runner_params().fps_idling.fps_idle,
        }

    def _query_get_theme(self, **_kwargs: Any) -> dict[str, Any]:
        """Return current theme and available themes."""
        return {
            "current": self._current_theme,
            "available": [str(t) for t in self._themes],
        }

    @trace
    def _emit_event(self, event: RemoteEventHandlerInvocation) -> None:
        """Stamp scene_id and queue for delivery to the Hub.

        D21: the display no longer dispatches interactions locally via
        ``DomainPump.route_interaction``. The ``remote_dispatch``
        handler on each element sends the ``RemoteEventHandlerInvocation`` to
        the Hub, where the real handler fires. This method is the
        socket-send path the ``remote_dispatch`` closure captures.
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

    # -- Tier 3 write handlers ------------------------------------------------

    def _query_set_window_settings(self, **kwargs: Any) -> dict[str, Any]:
        """Modify window settings. Only provided fields are changed."""
        changed: dict[str, Any] = {}

        if "opacity" in kwargs:
            val = float(kwargs["opacity"])
            val = max(0.1, min(1.0, val))
            self._opacity = val
            self._set_glfw_opacity(opacity=val)
            changed["opacity"] = val

        if "font_scale" in kwargs:
            val = float(kwargs["font_scale"])
            val = max(0.5, min(3.0, round(val, 1)))
            self._font_scale = val
            changed["font_scale"] = val

        if "decorated" in kwargs:
            decorated = bool(kwargs["decorated"])
            self._decorated = decorated
            self._set_glfw_decorated(decorated=decorated)
            changed["decorated"] = decorated

        if "fps_idle" in kwargs:
            from imgui_bundle import hello_imgui

            fps = float(kwargs["fps_idle"])
            fps = max(1.0, min(120.0, fps))
            hello_imgui.get_runner_params().fps_idling.fps_idle = fps
            changed["fps_idle"] = fps

        return {"changed": changed}

    def _query_set_frame_state(
        self, frame_id: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        """Modify frame state."""
        if not frame_id:
            msg = "frame_id is required"
            raise ValueError(msg)
        frame = self._scene_manager.frames.get(frame_id)
        if frame is None:
            msg = f"frame '{frame_id}' not found"
            raise LookupError(msg)
        changed: dict[str, Any] = {}

        if "minimized" in kwargs:
            frame.minimized = bool(kwargs["minimized"])
            changed["minimized"] = frame.minimized
        elif "collapsed" in kwargs:
            frame.minimized = bool(kwargs["collapsed"])
            changed["minimized"] = frame.minimized

        return {"frame_id": frame_id, "changed": changed}

    def _query_set_theme(self, theme: str = "", **_kwargs: Any) -> dict[str, Any]:
        """Set the display theme via query path."""
        if not theme:
            msg = "theme name is required"
            raise ValueError(msg)
        self._apply_theme(theme)
        return {"theme": self._current_theme}

    def client_name(self, fd: int) -> str | None:
        """Return the display name for a connected client, or ``None``."""
        return self._socket_server.client_names.get(fd)

    def _handle_register_menu(
        self, sock: socket.socket, msg: RegisterMenuMessage
    ) -> None:
        """Register menu items owned by this client into the Applications menu."""
        logger.info(
            "RegisterMenuMessage from fd=%s: %d items",
            sock.fileno(),
            len(msg.items),
        )
        try:
            fd = sock.fileno()
        except OSError:
            return
        self._menu_manager.handle_register_menu(fd, msg.items)

    def _handle_scene(self, sock: socket.socket, msg: SceneMessage) -> None:
        if msg.frame_id is not None:
            self._handle_framed_scene(sock, msg)
            return
        try:
            fd = sock.fileno()
        except OSError:
            return
        self._wrap_abc_elements(msg)
        self._scene_manager.handle_scene(msg, fd)
        self._route_to_domain_display(msg)
        ack = AckMessage(scene_id=msg.id, ts=time.time())
        self._socket_server.send_to_client(sock, ack)
        if self._test_auto_click:
            self._auto_click_buttons(msg)

    def _handle_framed_scene(self, sock: socket.socket, msg: SceneMessage) -> None:
        """Route a scene into a frame, creating the frame if needed."""
        try:
            fd = sock.fileno()
        except OSError:
            return
        self._wrap_abc_elements(msg)
        self._scene_manager.handle_framed_scene(msg, fd)
        self._route_to_domain_display(msg)
        ack = AckMessage(scene_id=msg.id, ts=time.time())
        self._socket_server.send_to_client(sock, ack)
        if self._test_auto_click:
            self._auto_click_buttons(msg)

    def _wrap_abc_elements(self, msg: SceneMessage) -> None:
        """Install remote_dispatch handlers on deserialized ABC elements.

        After native deserialization, ABC elements carry their Hub-side
        handlers. This method replaces them with ``remote_dispatch``
        wrappers so clicks route back to the Hub instead of executing
        locally. Must run BEFORE ``_route_to_domain_display`` so the
        DomainPump sees wrapped elements.
        """
        from punt_lux.domain.element_abc import Element as AbcElement

        for elem in msg.elements:
            if isinstance(elem, AbcElement):
                elem.wrap_handlers_for_remote(self._emit_event)

    def _route_to_domain_display(self, msg: SceneMessage) -> None:
        """Mirror basics-only scenes through Display.apply (PR 1 dual-write)."""
        self._domain_pump.route(msg)

    def _auto_click_buttons(self, msg: SceneMessage) -> None:
        """Enqueue synthetic interactions for testable elements (test mode).

        Synthetic events run BEFORE the first render loop assigns
        ``self._current_scene_id`` from ``_render_scene_tab``.
        Without stamping the scene id here, ``_emit_event`` would set
        ``scene_id=None`` and ``DomainPump.route_interaction`` would
        silently drop every synthetic button click.  Save / restore the
        prior value so the render loop's later assignment is undisturbed.
        """
        prior_scene_id = self._current_scene_id
        self._current_scene_id = msg.id
        try:
            self._auto_click_emit_loop(msg)
        finally:
            self._current_scene_id = prior_scene_id

    def _auto_click_emit_loop(self, msg: SceneMessage) -> None:
        """Per-element synthetic-interaction emit loop (see _auto_click_buttons)."""
        for elem in msg.elements:
            if elem.kind == "button" and not getattr(elem, "disabled", False):
                eid: str = getattr(elem, "id", "")
                action: str = getattr(elem, "action", None) or eid
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=eid,
                        action=action,
                        event_kind="button_clicked",
                        ts=time.time(),
                        value=True,
                    )
                )
            elif isinstance(elem, SliderElement):
                val: int | float = int(elem.value) if elem.integer else elem.value
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=val,
                    )
                )
            elif isinstance(elem, CheckboxElement):
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action=elem.action,
                        event_kind="value_changed",
                        ts=time.time(),
                        value=not elem.value,
                    )
                )
            elif isinstance(elem, ComboElement):
                item_text = (
                    elem.items[elem.selected]
                    if 0 <= elem.selected < len(elem.items)
                    else ""
                )
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value={"index": elem.selected, "item": item_text},
                    )
                )
            elif isinstance(elem, InputTextElement):
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )
            elif isinstance(elem, RadioElement):
                item_text = (
                    elem.items[elem.selected]
                    if 0 <= elem.selected < len(elem.items)
                    else ""
                )
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value={"index": elem.selected, "item": item_text},
                    )
                )
            elif isinstance(elem, ColorPickerElement):
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )
            elif isinstance(elem, SelectableElement):
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=elem.id,
                        action="clicked",
                        ts=time.time(),
                        value=not elem.selected,
                    )
                )

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
        self._menu_manager.check_world_menu_background_click(imgui)
        self._menu_manager.render_world_panel(imgui)

        # Render framed scenes (workspace model)
        self._render_frames(imgui)

        sm = self._scene_manager
        if not sm.scenes:
            return

        if len(sm.scenes) == 1:
            # Single scene: render directly without tab bar chrome
            scene_id = sm.scene_order[0]
            self._render_scene_tab(scene_id)
            return

        # Multiple scenes: render closable tab bar
        if imgui.begin_tab_bar("##lux_scenes"):
            closed_tabs: list[str] = []
            for scene_id in list(sm.scene_order):
                scene = sm.scenes[scene_id]
                label = scene.title or scene_id
                closable = True
                selected, still_open = imgui.begin_tab_item(
                    f"{label}##{scene_id}", closable
                )
                if selected:
                    sm.active_tab = scene_id
                    self._render_scene_tab(scene_id)
                    imgui.end_tab_item()
                if still_open is not None and not still_open:
                    closed_tabs.append(scene_id)
            imgui.end_tab_bar()
            for sid in closed_tabs:
                sm.dismiss_scene(sid)

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

    _DOCK_BAR_HEIGHT = 28.0

    def _apply_fit_all(self) -> bool:
        """If fit-all was requested, restore all frames and compute tile layout.

        Returns True when fitting is active (callers should use
        ``Cond_.always`` for position/size).
        """
        if not self._fit_all_frames:
            return False
        self._fit_all_frames = False
        frames = list(self._scene_manager.frames.values())
        for f in frames:
            f.minimized = False
        return True

    @staticmethod
    def _compute_tile_layout(
        imgui: Any,
        region: Any,
        frames: list[Frame],
    ) -> dict[str, tuple[float, float, float, float]]:
        """Compute tiled positions for frames that fill the content region.

        Returns a dict of frame_id -> (x, y, w, h).  Frames are arranged
        in a grid with roughly equal-sized cells.
        """
        import math

        n = len(frames)
        if n == 0:
            return {}
        origin = imgui.get_cursor_screen_pos()
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        gap = 4.0
        cell_w = (region.x - gap * (cols + 1)) / cols
        cell_h = (region.y - gap * (rows + 1)) / rows
        # Floor prevents zero/negative cells; frames may extend past the
        # viewport when the window is very small, but ImGui scroll handles it.
        cell_w = max(cell_w, 200.0)
        cell_h = max(cell_h, 150.0)
        result: dict[str, tuple[float, float, float, float]] = {}
        for i, f in enumerate(frames):
            col = i % cols
            row = i // cols
            x = origin.x + gap + col * (cell_w + gap)
            y = origin.y + gap + row * (cell_h + gap)
            result[f.frame_id] = (x, y, cell_w, cell_h)
        return result

    def _render_single_frame(
        self,
        frame: Frame,
        imgui: Any,
        *,
        fitting: bool,
        tile_layout: dict[str, tuple[float, float, float, float]],
        default_size: tuple[float, float],
    ) -> tuple[str | None, bool]:
        """Render one frame window.

        Returns (result, hovered) where result is 'closed', 'minimized',
        or None, and hovered indicates the mouse is over this frame.
        """
        if fitting and frame.frame_id in tile_layout:
            cond = imgui.Cond_.always.value
            x, y, fw, fh = tile_layout[frame.frame_id]
        else:
            cond = imgui.Cond_.first_use_ever.value
            x = self._CASCADE_BASE_X + frame.cascade_index * self._CASCADE_DX
            y = self._CASCADE_BASE_Y + frame.cascade_index * self._CASCADE_DY
            fw = float(frame.initial_size[0]) if frame.initial_size else default_size[0]
            fh = float(frame.initial_size[1]) if frame.initial_size else default_size[1]
        imgui.set_next_window_pos((x, y), cond)
        imgui.set_next_window_size((fw, fh), cond)
        if self._scene_manager.focus_frame_id == frame.frame_id:
            imgui.set_next_window_focus()
            self._scene_manager.focus_frame_id = None
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
            # Collapse triangle clicked -- minimize to dock bar.
            # Skip when docked: ImGui reports expanded=False during
            # docking transitions.
            if not imgui.is_window_docked():
                imgui.set_window_collapsed(False)
                imgui.end()
                return "minimized", hovered
            imgui.end()
            return None, hovered
        self._render_frame_contents(frame, imgui)
        imgui.end()
        return None, hovered

    def _render_frames(self, imgui: Any) -> None:
        """Render each frame as an ImGui inner window."""
        # Default frame size: 75% of content region (first use only).
        region = imgui.get_content_region_avail()
        frame_w = max(400.0, region.x * self._FRAME_FILL)
        frame_h = max(300.0, region.y * self._FRAME_FILL)

        sm = self._scene_manager
        fitting = self._apply_fit_all()
        tile_layout: dict[str, tuple[float, float, float, float]] = {}
        if fitting:
            tile_layout = self._compute_tile_layout(
                imgui, region, list(sm.frames.values())
            )

        closed_frames: list[str] = []
        minimized_frames: list[str] = []
        any_frame_hovered = False
        for frame in list(sm.frames.values()):
            if frame.minimized:
                continue
            result, hovered = self._render_single_frame(
                frame,
                imgui,
                fitting=fitting,
                tile_layout=tile_layout,
                default_size=(frame_w, frame_h),
            )
            any_frame_hovered = any_frame_hovered or hovered
            if result == "closed":
                closed_frames.append(frame.frame_id)
            elif result == "minimized":
                minimized_frames.append(frame.frame_id)
        for fid in closed_frames:
            self._close_frame(fid)
        for fid in minimized_frames:
            sm.frames[fid].minimized = True
        # Dock bar for minimized frames
        self._render_dock_bar(imgui, any_frame_hovered=any_frame_hovered)

    def _render_dock_bar(self, imgui: Any, *, any_frame_hovered: bool = False) -> None:
        """Render a bottom dock bar showing minimized frames as pills.

        *any_frame_hovered* is True when the mouse is over a visible frame
        window.  When set, pill clicks are suppressed to prevent restoring
        a frame when the user clicks on a frame that overlaps the dock bar.
        """
        minimized = [f for f in self._scene_manager.frames.values() if f.minimized]
        if not minimized:
            return

        from imgui_bundle import ImVec2

        viewport = imgui.get_main_viewport()
        bar_h = self._DOCK_BAR_HEIGHT
        bar_y = viewport.pos.y + viewport.size.y - bar_h
        bar_x = viewport.pos.x
        bar_w = viewport.size.x

        # Draw bar background on the foreground draw list so it's
        # always visible regardless of window stacking.
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()

        # Derive colors from the active theme.
        bar_bg = imgui.get_color_u32(style.color_(imgui.Col_.title_bg))
        border_col = imgui.get_color_u32(style.color_(imgui.Col_.border))
        text_col = imgui.get_color_u32(style.color_(imgui.Col_.text))

        draw.add_rect_filled(
            ImVec2(bar_x, bar_y),
            ImVec2(bar_x + bar_w, bar_y + bar_h),
            bar_bg,
        )
        draw.add_line(
            ImVec2(bar_x, bar_y),
            ImVec2(bar_x + bar_w, bar_y),
            border_col,
            1.0,
        )

        # Pill layout -- use raw mouse hit-testing instead of an invisible
        # ImGui window.  The dock bar renders on the foreground draw list
        # which has no window in the z-order, so invisible_button widgets
        # inside a helper window never receive clicks reliably.
        pill_pad = 6.0
        pill_h = bar_h - pill_pad * 2.0
        pill_x = bar_x + pill_pad
        pill_y = bar_y + pill_pad
        pill_gap = 4.0
        max_x = bar_x + bar_w - pill_pad

        pill_normal = imgui.get_color_u32(style.color_(imgui.Col_.button))
        pill_hovered = imgui.get_color_u32(style.color_(imgui.Col_.button_hovered))

        mouse = imgui.get_mouse_pos()
        # Accept clicks when no frame window or ImGui item is under the
        # cursor.  The previous is_window_hovered(any_window) guard was
        # always true because dock_space_over_viewport covers the entire
        # viewport, blocking all pill clicks.  We now use the explicit
        # any_frame_hovered flag computed during frame rendering.
        clicked = (
            imgui.is_mouse_clicked(imgui.MouseButton_.left)
            and not imgui.is_any_item_hovered()
            and not any_frame_hovered
        )

        for frame in minimized:
            text_size = imgui.calc_text_size(frame.title)
            pill_w = text_size.x + 16.0

            # Truncate: if this pill would overflow, show ellipsis.
            if pill_x + pill_w > max_x:
                ellipsis_size = imgui.calc_text_size("...")
                ey = pill_y + (pill_h - ellipsis_size.y) * 0.5
                draw.add_text(ImVec2(pill_x, ey), text_col, "...")
                break

            p_min = ImVec2(pill_x, pill_y)
            p_max = ImVec2(pill_x + pill_w, pill_y + pill_h)

            # Raw hit-test: is the mouse inside this pill rect?
            hovered = p_min.x <= mouse.x <= p_max.x and p_min.y <= mouse.y <= p_max.y

            bg = pill_hovered if hovered else pill_normal
            draw.add_rect_filled(p_min, p_max, bg, 4.0)

            text_y = pill_y + (pill_h - text_size.y) * 0.5
            draw.add_text(ImVec2(pill_x + 8.0, text_y), text_col, frame.title)

            if hovered and clicked:
                frame.minimized = False
                self._scene_manager.focus_frame_id = frame.frame_id

            pill_x += pill_w + pill_gap

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
                frame_empty = self._scene_manager.dismiss_framed_scene(frame, sid)
                if frame_empty:
                    self._close_frame(frame.frame_id)

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
        ws = self._scene_manager.widget_state_for(scene_id)
        if ws is not None:
            self._widget_state = ws
            self._table_renderer.widget_state = ws
            self._element_renderer.widget_state = ws
        # ``_emit_event`` stamps scene_id from ``self._current_scene_id``
        # for any RemoteEventHandlerInvocation whose scene_id is None —
        # without this assignment, clicks inside framed scenes carried
        # whatever ``_render_scene_tab`` last set (stale or None), so
        # ``DomainPump.route_interaction`` silently dropped them.
        self._current_scene_id = scene_id
        self._element_renderer.current_scene_id = scene_id
        scene = frame.scenes[scene_id]
        for elem in scene.elements:
            self._paint_element(elem)

    @trace
    def _paint_element(self, elem: Element) -> None:
        """Dispatch one element to its renderer (ImGui factory or legacy path)."""
        if isinstance(elem, TextElement):
            self._imgui_renderer_factory(elem).render()
        else:
            self._element_renderer.render_element(elem)

    def _close_frame(self, frame_id: str, *, notify: bool = True) -> None:
        """Remove a frame and all its scenes.

        When *notify* is True, a ``frame_close`` event is sent to all
        contributing clients (``owner_fds``).  Used for user-initiated
        close and tab close.  When False, no events are emitted -- used
        during disconnect cleanup where the departing client's fd is
        already removed and surviving clients should not be notified.
        """
        # Capture owner_fds before SceneManager removes the frame.
        frame = self._scene_manager.frames.get(frame_id)
        owner_fds = set(frame.owner_fds) if frame is not None else set()
        self._scene_manager.close_frame(frame_id)
        if notify and owner_fds:
            close_event = RemoteEventHandlerInvocation(
                element_id=frame_id,
                action="frame_close",
                ts=time.time(),
            )
            for ofd in owner_fds:
                owner_sock = self._socket_server.fd_to_client.get(ofd)
                if owner_sock is not None:
                    self._socket_server.send_to_client(owner_sock, close_event)

    def _render_scene_tab(self, scene_id: str) -> None:
        """Render a single scene's elements with its own widget state."""
        sm = self._scene_manager
        self._current_scene_id = scene_id
        self._element_renderer.current_scene_id = scene_id
        ws = sm.widget_state_for(scene_id)
        if ws is not None:
            self._widget_state = ws
            self._table_renderer.widget_state = ws
            self._element_renderer.widget_state = ws
        scene = sm.scenes[scene_id]
        if scene.title and len(sm.scenes) == 1:
            from imgui_bundle import imgui

            imgui.separator_text(scene.title)
        for elem in scene.elements:
            if isinstance(elem, TextElement):
                self._imgui_renderer_factory(elem).render()
            else:
                self._element_renderer.render_element(elem)

    # Element rendering delegated to ElementRenderer -- see element_renderer.py.

    # -- event flushing ----------------------------------------------------

    def _record_queued_events(self) -> None:
        """Copy queued events into the introspection ring buffer."""
        for event in self._event_queue:
            self._query_dispatcher.record_event(
                {
                    "element_id": event.element_id,
                    "action": event.action,
                    "event_kind": event.event_kind,
                    "value": event.value,
                    "timestamp": event.ts if event.ts is not None else time.time(),
                }
            )

    @trace
    def _dispatch_queued_events(self) -> None:
        """Send queued events to the owning client or broadcast."""
        for event in self._event_queue:
            is_world_menu = (
                event.action == "menu"
                and isinstance(event.value, dict)
                and event.value.get("menu") == "World"
            )
            owner_fd = (
                self._menu_manager.menu_owners.get(event.element_id)
                if is_world_menu
                else None
            )
            if owner_fd is None and event.scene_id:
                owner_fd = self._scene_manager.scene_to_owner.get(event.scene_id)
            if owner_fd is not None:
                target = self._socket_server.fd_to_client.get(owner_fd)
                if target is not None:
                    self._socket_server.send_to_client(target, event)
            else:
                for client in list(self._socket_server.clients):
                    self._socket_server.send_to_client(client, event)

    def _flush_events(self) -> None:
        if not self._event_queue:
            return
        self._record_queued_events()
        if self._socket_server.clients:
            self._dispatch_queued_events()
        self._event_queue.clear()
