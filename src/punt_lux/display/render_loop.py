"""The ImGui render loop, with non-blocking Unix socket IPC.

Polls I/O every frame with zero-timeout ``select()`` -- no threads/asyncio.
Pillow imports at module level; ImGui and OpenGL imports are deferred to
method bodies, so unit tests can import this without a GPU (``run()`` needs one).
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.display.auto_click import AutoClicker
from punt_lux.display.client_queries import ClientQueries
from punt_lux.display.content_message_gate import ContentMessageGate
from punt_lux.display.dock_bar import DockBar
from punt_lux.display.exit_signal import ExitSignal
from punt_lux.display.frame_placement import FramePlacement
from punt_lux.display.frame_presentation import FramePresentation
from punt_lux.display.frame_tiling import FrameTiling
from punt_lux.display.frame_turn import FrameTurn
from punt_lux.display.hub_reconciliation import HubReconciliation
from punt_lux.display.identity_guard import IdentityGuard
from punt_lux.display.interaction_delivery import InteractionDelivery
from punt_lux.display.menus.frame_info_button import FrameInfoButton
from punt_lux.display.pending_interactions import PendingInteractions
from punt_lux.display.query_dispatcher import QueryRouter
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.replica import Frame, SceneReplica, WidgetState
from punt_lux.display.replica.menu_replica import MenuReplica, OwnMenus
from punt_lux.display.setup import DisplaySetup
from punt_lux.display.socket_server import SocketListener, SocketListenerCallbacks
from punt_lux.display.terminal.activity import TerminalActivity
from punt_lux.display.texture_cache import TextureCache
from punt_lux.display.window_chrome import WindowChrome
from punt_lux.display.window_settings import WindowSettings
from punt_lux.kernel.tracing import trace
from punt_lux.service.display_paths import DisplayPaths
from punt_lux.wire.model import (
    CallbackMenuMessage,
    ConnectMessage,
    HubManifestMessage,
    MenuMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    ThemeMessage,
)
from punt_lux.wire.model.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from punt_lux.display.client_sender import ClientSender
    from punt_lux.display.cross_host_pump import CrossHostPump
    from punt_lux.display.replica.address_rendering import AddressRendering
    from punt_lux.wire.model import Message
    from punt_lux.wire.model.identity import HubId

logger = logging.getLogger(__name__)

# Sentinel fd for a scene whose owning client disconnected with no co-owner;
# it persists until the user closes the frame or a new client adopts it.
_ORPHAN_FD = -1

# SPIKE: keep full frame rate this long after terminal output stops.


class RenderLoop:
    """The ImGui render loop, with non-blocking Unix socket IPC."""

    _socket_path: Path
    _socket_listener: SocketListener
    _sender: ClientSender
    _scenes: SceneReplica
    _addressing: AddressRendering
    _event_queue: list[RemoteEventHandlerInvocation]
    _interaction_delivery: InteractionDelivery
    _pending: PendingInteractions
    _textures: TextureCache
    _widget_state: WidgetState
    _menus: MenuReplica
    _frame_info_button: FrameInfoButton
    _fit_all_frames: bool
    _settings: WindowSettings
    _test_auto_click: bool
    _current_scene_id: str | None
    _query_router: QueryRouter
    _queries: ClientQueries
    _display_paths: DisplayPaths
    _imgui_renderer_factory: ImGuiRendererFactory
    _luxd_factory: Any  # JsonElementFactory, declared Any to avoid an import cycle
    _identity: IdentityGuard
    _hub_reconciliation: HubReconciliation
    _content_gate: ContentMessageGate
    _exit_signal: ExitSignal
    _turn: FrameTurn

    def __new__(
        cls,
        socket_path: str | None = None,
        *,
        test_auto_click: bool = False,
        cross_host_listener: CrossHostPump | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._display_paths = DisplayPaths(Path(socket_path) if socket_path else None)
        self._socket_path = self._display_paths.socket_path
        self._scenes = SceneReplica(
            on_scene_replaced=self._drain_stale_events,
            on_terminals_held=TerminalActivity.retain,
        )
        # Inline import (like the factory wiring below) keeps this off efferent.
        from punt_lux.display.replica.address_rendering import AddressRendering

        self._addressing = AddressRendering()
        self._settings = WindowSettings()
        self._fit_all_frames = False
        self._menus = MenuReplica(
            emit_event=self._emit_event,
            on_raise_frame=self._raise_frame,
            get_frames=lambda: self._scenes.frames,
            own=OwnMenus(
                settings=self._settings,
                get_frames=lambda: self._scenes.frames,
                addressing=self._addressing,
                on_clear_all=self._clear_all,
                on_fit_all=self._request_fit_all,
                on_raise_frame=self._raise_frame_unscoped,
                chrome=WindowChrome(),
            ),
        )
        self._frame_info_button = FrameInfoButton(
            frame_for=self._scenes.frame, facts_for=self._scenes.owner_facts_for
        )
        # QueryRouter must precede SocketListener -- it supplies on_error.
        self._query_router = QueryRouter(self._scenes)
        socket_callbacks = SocketListenerCallbacks(
            on_message=self._handle_message,
            on_client_disconnected=self._on_client_disconnected,
            on_error=self._query_router.record_error,
        )
        self._socket_listener, self._sender = SocketListener.with_sender(
            socket_callbacks
        )
        self._query_router.register_handler(
            "list_clients", self._socket_listener.client_report
        )
        self._query_router.register_handler("list_menus", self._menus.inventory_report)
        self._interaction_delivery = InteractionDelivery(
            socket_listener=self._socket_listener,
            sender=self._sender,
            scenes=self._scenes,
        )
        self._identity = IdentityGuard(
            socket_listener=self._socket_listener,
            record_error=self._query_router.record_error,
        )
        self._hub_reconciliation = HubReconciliation(
            socket_listener=self._socket_listener,
            scenes=self._scenes,
            record_error=self._query_router.record_error,
            identity=self._identity,
        )
        self._content_gate = ContentMessageGate(
            menus=self._menus,
            apply_theme=self._settings.apply_theme,
            identity=self._identity,
        )
        # Bind a fail-loud decode factory to the shared container-dispatch
        # target. Inbound scenes cross as pickles (SceneCodec), so the display
        # never JSON-decodes a tree and this is not on the scene path; it is the
        # sentinel for any JSON element decode here. The Display may not own
        # business publish, so a container decoded through it fails loud
        # (RaisingRendererFactory + RaisingPublishSink), never running locally.
        from punt_lux.display.replica.emit import NoOpEmit
        from punt_lux.wire.model.element_factory import JsonElementFactory
        from punt_lux.wire.model.elements.container_dispatch import (
            dispatch as _container_dispatch,
        )
        from punt_lux.wire.model.raising_publish_sink import RaisingPublishSink

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
        self._widget_state = WidgetState()  # active scene's state (swapped)
        self._test_auto_click = test_auto_click
        self._current_scene_id = None
        self._imgui_renderer_factory = ImGuiRendererFactory(
            widget_state=self._widget_state,
            texture_cache=self._textures,
            # Display-tier emit is a no-op; interactions route to the Hub.
            emit=lambda _msg: None,
        )

        # Register display-specific query handlers that need ImGui state.
        self._queries = ClientQueries(
            sender=self._sender,
            query_router=self._query_router,
            scenes=self._scenes,
            geometry=self._imgui_renderer_factory.geometry.recorder,
            settings=self._settings,
            screenshot_dir=self._socket_path.parent / "screenshots",
        )
        self._turn = FrameTurn.standard(
            sockets=self._socket_listener,
            sender=self._sender,
            cross_host=cross_host_listener,
            queries=self._queries,
        )
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
        from imgui_bundle import immapp

        runner_params = DisplaySetup.parameters()
        runner_params.callbacks.show_menus = self._menus.show_menus
        runner_params.callbacks.post_init = self._on_post_init
        runner_params.callbacks.show_gui = functools.partial(
            self._turn.run, self._pump_terminals, self._render_scene, self._flush_events
        )
        runner_params.callbacks.before_swap = self._turn.before_swap
        runner_params.callbacks.after_swap = self._turn.after_swap
        runner_params.callbacks.before_exit = self._on_exit
        self._exit_signal = ExitSignal(runner_params)

        addons = DisplaySetup.addons()
        immapp.run(runner_params, addons)

    def _announce_listening(self) -> None:
        """Record the pid and log once the socket claim has succeeded."""
        self._display_paths.write_pid()
        logger.info("Display server listening on %s", self._socket_path)

    # -- ImGui callbacks ---------------------------------------------------

    def _on_post_init(self) -> None:
        """Initialize graphics resources once the OpenGL context is ready."""
        DisplaySetup.post_init()
        self._settings.start()

    def _clear_all(self) -> None:
        """Discard all frames, scenes, and widget state from the menu callback."""
        self._scenes.dispose_all_frames()
        self._handle_clear()

    def _raise_frame(self, frame_id: str, hub: HubId) -> None:
        """Raise a replicated menu's frame in its owning Hub's scope."""
        self._scenes.raise_frame(frame_id, hub)

    def _raise_frame_unscoped(self, frame_id: str) -> None:
        self._scenes.raise_frame(frame_id)

    def _request_fit_all(self) -> None:
        """Request a fit-all layout from the menu."""
        self._fit_all_frames = True

    _pump_terminals = staticmethod(TerminalActivity.pump)

    def _on_exit(self) -> None:
        """Release graphics resources before the window closes."""
        TerminalActivity.close()
        self._textures.cleanup()
        self._turn.shutdown()  # the cross-host listen socket and pending peers
        self._socket_listener.shutdown()
        self._socket_path.unlink(missing_ok=True)
        self._display_paths.remove_pid()
        logger.info("Display server stopped")

    # -- menu bar ----------------------------------------------------------

    # -- socket callbacks ---------------------------------------------------

    def _on_client_disconnected(self, fd: int) -> None:
        """Reassign this client's scenes; retire a departed Hub's own menu."""
        self._scenes.reassign_scenes_of(fd, _ORPHAN_FD)
        hub = self._socket_listener.hub_id_of(fd)
        self._menus.forget_hub(hub) if hub is not None else None
        self._addressing.forget_connection(hub, str(fd)) if hub is not None else None

    # -- message handling --------------------------------------------------

    def _handle_message(self, sock: socket.socket, msg: Message) -> None:
        """Dispatch a scene/menu/theme-mutating message; read-only kinds delegate."""
        if isinstance(msg, SceneMessage):
            self._handle_scene(sock, msg)
        elif isinstance(msg, MenuMessage):
            self._content_gate.handle_agent_menus(sock, msg)
        elif isinstance(msg, CallbackMenuMessage):
            self._content_gate.handle_callback_menus(sock, msg)
        elif isinstance(msg, ThemeMessage):
            self._content_gate.handle_theme(sock, msg)
        elif isinstance(msg, ConnectMessage):
            self._handle_connect(sock, msg)
        elif isinstance(msg, HubManifestMessage):
            self._handle_hub_manifest(sock, msg)
        else:
            self._queries.handle(sock, msg)

    def _handle_clear(self) -> None:
        """Drop all scenes and reset per-frame state — the World-menu 'clear all'."""
        self._interaction_delivery.compensate_evicted(self._pending.evict_all())
        self._scenes.clear_all()
        self._event_queue.clear()
        self._widget_state = WidgetState()

    def _handle_connect(self, sock: socket.socket, msg: ConnectMessage) -> None:
        """Record the peer identity, preempt stale Hubs, and register title labels."""
        fd = sock.fileno()
        self._hub_reconciliation.handle_connect(sock, msg)
        hub = self._socket_listener.hub_id_of(fd)
        self._addressing.note_connection(hub, str(fd)) if hub is not None else None

    def _handle_hub_manifest(
        self, sock: socket.socket, msg: HubManifestMessage
    ) -> None:
        """Purge every scene a Hub manifest disowns (DES-068)."""
        self._hub_reconciliation.handle_manifest(sock, msg)

    @trace
    def _emit_event(self, event: RemoteEventHandlerInvocation) -> None:
        """Stamp scene_id and queue for delivery to the Hub.

        D21: the display dispatches no interactions locally. The
        ``remote_dispatch`` handler on each element sends the
        ``RemoteEventHandlerInvocation`` to the Hub, where the real handler
        fires. This method is the socket-send path the ``remote_dispatch``
        closure captures.

        A menu-sourced event already carries its own routing hint
        (``hub_token``) and no scene -- stamping ``_current_scene_id`` onto it
        would make it look scene-owned and defeat that routing (W6), so the
        stamp is skipped whenever ``hub_token`` is set.
        """
        if event.scene_id is None and event.hub_token is None:
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
        """Route a scene into its frame, creating the frame if needed."""
        if self._hub_reconciliation.reject_scene_unless_hub(sock):
            return
        self._turn.scene_received(msg.id)
        self._wrap_abc_elements(msg)
        hub = self._hub_reconciliation.hub_of(sock)
        self._scenes.handle_framed_scene(msg, sock.fileno(), hub)
        self._sender.hold_ack(sock, msg.id)  # acked once a swap has completed
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

        imgui.get_style().font_scale_main = self._settings.font_scale

        DisplaySetup.background(imgui)

        # World menu: background click to toggle, floating panel.
        self._menus.check_world_menu_background_click(imgui)
        self._menus.render_world_panel(imgui)

        # Every scene renders inside a frame (workspace model); there is no
        # unframed scene surface — the Hub frames every scene at the boundary.
        self._render_frames(imgui)

        # Info popup in ImGui's popup layer, above its frame: after the frames, so
        # a glyph press sees it still open on the frame ImGui shuts it.
        self._frame_info_button.render_popup(imgui)

        # Promote this frame's rects into the snapshot the next frame's query
        # reads (that query runs in poll_clients before the next render).
        self._imgui_renderer_factory.geometry.complete()

    # Cascade layout: each new frame offsets from the previous one.
    _CASCADE_BASE_X = 30.0
    _CASCADE_BASE_Y = 40.0
    _CASCADE_DX = 30.0
    _CASCADE_DY = 30.0
    _FRAME_FILL = 0.75

    _resolve_frame_flags = staticmethod(FramePresentation.flags)
    _cascaded_frame_size = staticmethod(FramePresentation.initial_size)

    def _apply_fit_all(self) -> bool:
        """Undock and tile visible frames without restoring closed ones."""
        if not self._fit_all_frames:
            return False
        self._fit_all_frames = False
        for frame in self._scenes.docked_frames():
            frame.restore()
        return True

    def _render_single_frame(
        self, frame: Frame, imgui: Any, placement: FramePlacement
    ) -> tuple[str | None, bool]:
        """Render a frame and return its close or minimize result and hover state."""
        # A fit-all pass tiles this frame if it has a computed rect; else cascade.
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
        label = self._addressing.frame_window_label(frame)
        expanded, still_open = imgui.begin(label, still_open, win_flags)
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
            self._frame_info_button.render(frame, imgui)
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
        DockBar(imgui, sm, self._addressing).render(any_frame_hovered=any_frame_hovered)

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
        if frame.hints.layout == "stack":
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
                self._scenes.departure.of_dismissal(frame, sid)

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
        self._turn.scene_painted(scene_id)
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
        """Deliver queued interactions within one frame budget; hold the rest."""
        if not self._event_queue and self._pending.is_empty:
            return
        self._record_queued_events()
        now = time.monotonic()
        self._pending.admit(self._event_queue, now)
        self._event_queue.clear()
        expired = self._pending.expire(now)
        if self._socket_listener.clients:
            removed, dropped = self._interaction_delivery.deliver(
                self._pending.pending_events()
            )
            self._pending.discard_delivered(removed)
            if dropped:
                self._interaction_delivery.compensate_evicted(
                    self._pending.compensate_dropped(dropped)
                )
        self._interaction_delivery.compensate_evicted(expired)
