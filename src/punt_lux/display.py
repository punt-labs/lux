# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Lux display server — ImGui render loop with non-blocking Unix socket IPC.

Listens on a Unix domain socket for protocol messages and renders scenes
using imgui-bundle. Socket I/O is polled every frame via ``select()`` with
zero timeout — no threads, no asyncio.

This module imports numpy and Pillow at module level but defers ImGui and
OpenGL imports to method bodies. It can be imported by unit tests (for state
machine testing) but ``run()`` requires a GPU-capable environment.
"""

from __future__ import annotations

import contextlib
import logging
import select
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from PIL import Image

from punt_lux.paths import (
    cleanup_stale_socket,
    default_socket_path,
    remove_pid_file,
    write_pid_file,
)
from punt_lux.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    AckMessage,
    CheckboxElement,
    ClearMessage,
    ColorPickerElement,
    ComboElement,
    FrameReader,
    InputTextElement,
    InteractionMessage,
    PingMessage,
    PongMessage,
    RadioElement,
    ReadyMessage,
    SceneMessage,
    SliderElement,
    UpdateMessage,
    encode_message,
)

if TYPE_CHECKING:
    from punt_lux.protocol import Element, Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Texture cache
# ---------------------------------------------------------------------------


class TextureCache:
    """Maps file paths to OpenGL texture IDs. Uploads on first access."""

    def __init__(self) -> None:
        self._textures: dict[str, int] = {}

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading if needed."""
        if path in self._textures:
            return self._textures[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            return None
        tex_id = _create_texture(path)
        if tex_id is not None:
            self._textures[path] = tex_id
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures."""
        import OpenGL.GL as GL

        for tex_id in self._textures.values():
            GL.glDeleteTextures(1, [tex_id])
        self._textures.clear()


def _create_texture(path: str) -> int | None:
    """Load an image file and upload it as an OpenGL texture."""
    import OpenGL.GL as GL

    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        logger.exception("Failed to load image: %s", path)
        return None

    data = np.array(img, dtype=np.uint8)
    h, w = data.shape[:2]

    tex_id: int = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexImage2D(
        GL.GL_TEXTURE_2D,
        0,
        GL.GL_RGBA,
        w,
        h,
        0,
        GL.GL_RGBA,
        GL.GL_UNSIGNED_BYTE,
        data,
    )
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return int(tex_id)


# ---------------------------------------------------------------------------
# Widget state (persistent across ImGui frames)
# ---------------------------------------------------------------------------


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def get(self, element_id: str, default: Any = None) -> Any:
        return self._state.get(element_id, default)

    def set(self, element_id: str, value: Any) -> None:
        self._state[element_id] = value

    def ensure(self, element_id: str, default: Any) -> Any:
        if element_id not in self._state:
            self._state[element_id] = default
        return self._state[element_id]

    def clear(self) -> None:
        self._state.clear()


# ---------------------------------------------------------------------------
# Color conversion helpers
# ---------------------------------------------------------------------------


def _parse_hex_color(hex_str: str) -> tuple[int, int, int, int]:
    """Parse a hex color string to (r, g, b, a) ints 0-255."""
    h = hex_str.lstrip("#")
    try:
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (r, g, b, 255)
        if len(h) == 8:
            r, g, b, a = (
                int(h[0:2], 16),
                int(h[2:4], 16),
                int(h[4:6], 16),
                int(h[6:8], 16),
            )
            return (r, g, b, a)
    except ValueError:
        logger.warning("Invalid hex color %r; using fallback white", hex_str)
    return (255, 255, 255, 255)


def _color_to_hex(r: float, g: float, b: float) -> str:
    """Convert float RGB (0-1) to hex string."""
    ri = int(max(0.0, min(1.0, r)) * 255)
    gi = int(max(0.0, min(1.0, g)) * 255)
    bi = int(max(0.0, min(1.0, b)) * 255)
    return f"#{ri:02X}{gi:02X}{bi:02X}"


def _hex_to_imgui_color(hex_str: str) -> int:
    """Convert hex string to ImGui packed color (ImU32)."""
    from imgui_bundle import ImVec4, imgui

    r, g, b, a = _parse_hex_color(hex_str)
    result: int = imgui.get_color_u32(
        ImVec4(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    )
    return result


def _widget_value(elem: Element) -> Any:
    """Extract the current widget value from an element for WidgetState."""
    if isinstance(elem, (SliderElement, CheckboxElement, InputTextElement)):
        return elem.value
    if isinstance(elem, (ComboElement, RadioElement)):
        return elem.selected
    if isinstance(elem, ColorPickerElement):
        r, g, b, _a = _parse_hex_color(elem.value)
        from imgui_bundle import ImVec4

        return ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
    return None


# ---------------------------------------------------------------------------
# Display server
# ---------------------------------------------------------------------------


class DisplayServer:
    """ImGui display server with non-blocking Unix socket IPC."""

    def __init__(
        self,
        socket_path: str | None = None,
        *,
        test_auto_click: bool = False,
    ) -> None:
        self._socket_path = Path(socket_path or str(default_socket_path()))
        self._server_sock: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._readers: dict[int, FrameReader] = {}  # fd -> reader
        self._current_scene: SceneMessage | None = None
        self._event_queue: list[InteractionMessage] = []
        self._textures = TextureCache()
        self._widget_state = WidgetState()
        self._test_auto_click = test_auto_click

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    # -- public entry point ------------------------------------------------

    def run(self) -> None:
        """Start the display server (blocking — ImGui owns the main loop)."""
        from imgui_bundle import hello_imgui, immapp

        runner_params = hello_imgui.RunnerParams()
        runner_params.app_window_params.window_title = "Lux Display"
        runner_params.app_window_params.window_geometry.size = (800, 600)
        runner_params.callbacks.post_init = self._on_post_init
        runner_params.callbacks.show_gui = self._on_frame
        runner_params.callbacks.before_exit = self._on_exit
        runner_params.fps_idling.fps_idle = 30.0

        immapp.run(runner_params)

    # -- ImGui callbacks ---------------------------------------------------

    def _on_post_init(self) -> None:
        """Called once the OpenGL context is ready."""
        self._setup_socket()
        write_pid_file(self._socket_path)
        logger.info("Display server listening on %s", self._socket_path)

    def _on_frame(self) -> None:
        """Called every frame by ImGui."""
        self._accept_connections()
        self._poll_clients()
        self._render_scene()
        self._flush_events()

    def _on_exit(self) -> None:
        """Called before the window closes."""
        self._textures.cleanup()
        for client in self._clients:
            client.close()
        self._clients.clear()
        self._readers.clear()
        if self._server_sock is not None:
            self._server_sock.close()
            self._server_sock = None
        self._socket_path.unlink(missing_ok=True)
        remove_pid_file(self._socket_path)
        logger.info("Display server stopped")

    # -- socket lifecycle --------------------------------------------------

    def _setup_socket(self) -> None:
        cleanup_stale_socket(self._socket_path)
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            if self._socket_path.is_socket():
                self._socket_path.unlink()
            else:
                msg = f"Path exists and is not a socket: {self._socket_path}"
                raise RuntimeError(msg)
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(str(self._socket_path))
        self._server_sock.listen(5)
        self._server_sock.setblocking(False)  # noqa: FBT003

    def _accept_connections(self) -> None:
        if self._server_sock is None:
            return
        readable, _, _ = select.select([self._server_sock], [], [], 0)
        if readable:
            try:
                conn, _ = self._server_sock.accept()
            except (BlockingIOError, OSError):
                return
            conn.setblocking(False)  # noqa: FBT003
            self._clients.append(conn)
            self._readers[conn.fileno()] = FrameReader()
            logger.debug("Client connected (total: %d)", len(self._clients))
            self._send_to_client(conn, ReadyMessage())

    def _poll_clients(self) -> None:
        if not self._clients:
            return
        readable, _, errored = select.select(self._clients, [], self._clients, 0)
        for sock in errored:
            self._remove_client(sock)
        for sock in readable:
            if sock in self._clients:
                self._read_from_client(sock)

    def _read_from_client(self, sock: socket.socket) -> None:
        reader = self._readers.get(sock.fileno())
        if reader is None:
            return
        try:
            data = sock.recv(65536)
            if not data:
                self._remove_client(sock)
                return
            reader.feed(data)
            if reader.buffer_size > MAX_MESSAGE_SIZE + HEADER_SIZE:
                logger.warning("Buffer overflow from fd %d", sock.fileno())
                self._remove_client(sock)
                return
            for msg in reader.drain_typed():
                self._handle_message(sock, msg)
                if sock not in self._clients:
                    return  # removed during handle (e.g. send failed)
        except (ConnectionError, OSError):
            self._remove_client(sock)
        except ValueError:
            logger.warning("Malformed message from fd %d, disconnecting", sock.fileno())
            self._remove_client(sock)

    def _remove_client(self, sock: socket.socket) -> None:
        if sock not in self._clients:
            return  # already removed — make idempotent
        self._clients.remove(sock)
        try:
            fd = sock.fileno()
        except OSError:
            fd = None
        if fd is not None:
            self._readers.pop(fd, None)
        with contextlib.suppress(OSError):
            sock.close()
        logger.debug("Client disconnected (remaining: %d)", len(self._clients))

    def _send_to_client(self, sock: socket.socket, msg: Message) -> None:
        try:
            sock.sendall(encode_message(msg))
        except (ConnectionError, OSError):
            self._remove_client(sock)

    # -- message handling --------------------------------------------------

    def _handle_message(self, sock: socket.socket, msg: Message) -> None:
        if isinstance(msg, SceneMessage):
            self._current_scene = msg
            self._event_queue.clear()
            self._widget_state.clear()
            self._send_to_client(sock, AckMessage(scene_id=msg.id, ts=time.time()))
            if self._test_auto_click:
                self._auto_click_buttons(msg)
        elif isinstance(msg, UpdateMessage):
            self._apply_update(msg)
            self._send_to_client(
                sock,
                AckMessage(scene_id=msg.scene_id, ts=time.time()),
            )
        elif isinstance(msg, ClearMessage):
            self._current_scene = None
            self._event_queue.clear()
        elif isinstance(msg, PingMessage):
            self._send_to_client(sock, PongMessage(ts=msg.ts, display_ts=time.time()))

    def _apply_update(self, msg: UpdateMessage) -> None:
        scene = self._current_scene
        if scene is None or scene.id != msg.scene_id:
            return
        elements = scene.elements
        for patch in msg.patches:
            idx = next(
                (
                    i
                    for i, e in enumerate(elements)
                    if getattr(e, "id", None) == patch.id
                ),
                None,
            )
            if idx is None:
                continue
            if patch.remove:
                elements.pop(idx)
                self._widget_state.set(patch.id, None)
            elif patch.set:
                elem = elements[idx]
                for k, v in patch.set.items():
                    if k in ("id", "kind"):
                        continue
                    if hasattr(elem, k):
                        setattr(elem, k, v)
                # Sync widget state so ImGui reflects patched values
                eid = getattr(elem, "id", None)
                if eid is not None and patch.set.keys() & {
                    "value",
                    "selected",
                    "items",
                }:
                    self._widget_state.set(eid, _widget_value(elem))

    def _auto_click_buttons(self, msg: SceneMessage) -> None:
        """Enqueue synthetic interactions for testable elements (test mode)."""
        for elem in msg.elements:
            if elem.kind == "button" and not getattr(elem, "disabled", False):
                eid: str = getattr(elem, "id", "")
                action: str = getattr(elem, "action", None) or eid
                self._event_queue.append(
                    InteractionMessage(
                        element_id=eid,
                        action=action,
                        ts=time.time(),
                        value=True,
                    )
                )
            elif isinstance(elem, SliderElement):
                val: int | float = int(elem.value) if elem.integer else elem.value
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=val,
                    )
                )
            elif isinstance(elem, CheckboxElement):
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )
            elif isinstance(elem, ComboElement):
                item_text = (
                    elem.items[elem.selected]
                    if 0 <= elem.selected < len(elem.items)
                    else ""
                )
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value={"index": elem.selected, "item": item_text},
                    )
                )
            elif isinstance(elem, InputTextElement):
                self._event_queue.append(
                    InteractionMessage(
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
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value={"index": elem.selected, "item": item_text},
                    )
                )
            elif isinstance(elem, ColorPickerElement):
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )

    # -- rendering ---------------------------------------------------------

    def _render_scene(self) -> None:
        from imgui_bundle import imgui

        if self._current_scene is None:
            imgui.text("Lux Display — waiting for scene...")
            return

        if self._current_scene.title:
            imgui.separator_text(self._current_scene.title)

        for elem in self._current_scene.elements:
            self._render_element(elem)

    _RENDERERS: ClassVar[dict[str, str]] = {
        "text": "_render_text",
        "button": "_render_button",
        "separator": "_render_separator",
        "image": "_render_image",
        "slider": "_render_slider",
        "checkbox": "_render_checkbox",
        "combo": "_render_combo",
        "input_text": "_render_input_text",
        "radio": "_render_radio",
        "color_picker": "_render_color_picker",
        "draw": "_render_draw",
    }

    def _render_element(self, elem: Element) -> None:
        method_name = self._RENDERERS.get(elem.kind)
        if method_name is not None:
            getattr(self, method_name)(elem)
        else:
            from imgui_bundle import imgui

            imgui.text(f"[unsupported element: {elem.kind}]")

    def _render_text(self, elem: Element) -> None:
        from imgui_bundle import ImVec4, imgui

        text_elem: Any = elem
        content: str = text_elem.content
        style: str | None = text_elem.style

        if style == "heading":
            imgui.separator_text(content)
        elif style == "caption":
            imgui.text_colored(ImVec4(0.6, 0.6, 0.6, 1.0), content)
        elif style == "code":
            imgui.indent(10.0)
            imgui.text(content)
            imgui.unindent(10.0)
        else:
            imgui.text_wrapped(content)

    def _render_button(self, elem: Element) -> None:
        from imgui_bundle import imgui

        btn: Any = elem
        label: str = btn.label
        eid: str = btn.id
        action: str = btn.action or eid
        disabled: bool = btn.disabled

        if disabled:
            imgui.begin_disabled()

        if imgui.button(f"{label}##{eid}"):
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action=action,
                    ts=time.time(),
                    value=True,
                )
            )

        if disabled:
            imgui.end_disabled()

    def _render_separator(self, _elem: Element) -> None:
        from imgui_bundle import imgui

        imgui.separator()

    def _render_image(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        img: Any = elem
        path: str | None = img.path
        width: int = img.width if img.width is not None else 200
        height: int = img.height if img.height is not None else 150

        tex_id = self._textures.get_or_load(path) if path else None
        if tex_id is not None:
            imgui.image(imgui.ImTextureRef(tex_id), ImVec2(width, height))
        else:
            alt: str = img.alt or path or "(image)"
            imgui.text(f"[{alt}]")

    def _render_slider(self, elem: Element) -> None:
        from imgui_bundle import imgui

        sl: Any = elem
        eid: str = sl.id
        label: str = sl.label
        v_min: float = sl.min
        v_max: float = sl.max
        fmt: str = sl.format
        is_int: bool = sl.integer

        current = self._widget_state.ensure(eid, sl.value)

        new_val: int | float
        if is_int:
            changed, new_val = imgui.slider_int(
                f"{label}##{eid}", int(current), int(v_min), int(v_max)
            )
        else:
            changed, new_val = imgui.slider_float(
                f"{label}##{eid}", float(current), float(v_min), float(v_max), fmt
            )

        if changed:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_checkbox(self, elem: Element) -> None:
        from imgui_bundle import imgui

        cb: Any = elem
        eid: str = cb.id
        label: str = cb.label

        current = self._widget_state.ensure(eid, cb.value)
        changed, new_val = imgui.checkbox(f"{label}##{eid}", current)
        if changed:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_combo(self, elem: Element) -> None:
        from imgui_bundle import imgui

        co: Any = elem
        eid: str = co.id
        label: str = co.label
        items: list[str] = co.items

        initial = max(0, min(co.selected, len(items) - 1)) if items else 0
        current = self._widget_state.ensure(eid, initial)
        if not items:
            imgui.text(f"{label}: (empty)")
            return
        if current < 0 or current >= len(items):
            current = 0
            self._widget_state.set(eid, current)
        changed, new_val = imgui.combo(f"{label}##{eid}", current, items)
        if changed:
            self._widget_state.set(eid, new_val)
            item_text = items[new_val] if 0 <= new_val < len(items) else ""
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value={"index": new_val, "item": item_text},
                )
            )

    def _render_input_text(self, elem: Element) -> None:
        from imgui_bundle import imgui

        it: Any = elem
        eid: str = it.id
        label: str = it.label
        hint: str = it.hint

        current = self._widget_state.ensure(eid, it.value)

        if hint:
            changed, new_val = imgui.input_text_with_hint(
                f"{label}##{eid}", hint, current
            )
        else:
            changed, new_val = imgui.input_text(f"{label}##{eid}", current)

        if changed:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_radio(self, elem: Element) -> None:
        from imgui_bundle import imgui

        rd: Any = elem
        eid: str = rd.id
        label: str = rd.label
        items: list[str] = rd.items

        current: int = self._widget_state.ensure(eid, rd.selected)

        if label:
            imgui.text(label)

        for i, item in enumerate(items):
            if imgui.radio_button(f"{item}##{eid}_{i}", current == i) and current != i:
                self._widget_state.set(eid, i)
                self._event_queue.append(
                    InteractionMessage(
                        element_id=eid,
                        action="changed",
                        ts=time.time(),
                        value={"index": i, "item": item},
                    )
                )
                current = i
            if i < len(items) - 1:
                imgui.same_line()

    def _render_color_picker(self, elem: Element) -> None:
        from imgui_bundle import ImVec4, imgui

        cp: Any = elem
        eid: str = cp.id
        label: str = cp.label
        hex_str: str = cp.value

        r, g, b, _a = _parse_hex_color(hex_str)
        initial = ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
        current = self._widget_state.ensure(eid, initial)

        changed, new_color = imgui.color_edit3(f"{label}##{eid}", current)
        if changed:
            self._widget_state.set(eid, new_color)
            hex_val = _color_to_hex(new_color[0], new_color[1], new_color[2])
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=hex_val,
                )
            )

    # -- draw element rendering --------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        draw: Any = elem
        eid: str = draw.id
        width: int = draw.width
        height: int = draw.height
        bg_color: str | None = draw.bg_color
        commands: list[dict[str, Any]] = draw.commands

        canvas_pos = imgui.get_cursor_screen_pos()
        canvas_min = ImVec2(canvas_pos.x, canvas_pos.y)
        canvas_max = ImVec2(canvas_pos.x + width, canvas_pos.y + height)
        draw_list = imgui.get_window_draw_list()

        draw_list.push_clip_rect(canvas_min, canvas_max, True)  # noqa: FBT003

        if bg_color is not None:
            draw_list.add_rect_filled(
                canvas_min, canvas_max, _hex_to_imgui_color(bg_color)
            )

        ox, oy = canvas_pos.x, canvas_pos.y
        for cmd in commands:
            try:
                self._dispatch_draw_cmd(draw_list, cmd, ox, oy)
            except (KeyError, IndexError, TypeError, ValueError):
                logger.debug("Skipping malformed draw command: %s", cmd)

        draw_list.pop_clip_rect()
        imgui.dummy(ImVec2(width, height))
        _ = eid  # used for future interaction tracking

    def _dispatch_draw_cmd(
        self,
        draw_list: Any,
        cmd: dict[str, Any],
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        cmd_type = cmd.get("cmd", "")
        color = _hex_to_imgui_color(cmd.get("color", "#FFFFFF"))
        thickness: float = cmd.get("thickness", 1.0)

        if cmd_type == "line":
            p1, p2 = cmd["p1"], cmd["p2"]
            draw_list.add_line(
                ImVec2(ox + p1[0], oy + p1[1]),
                ImVec2(ox + p2[0], oy + p2[1]),
                color,
                thickness,
            )
        elif cmd_type == "rect":
            self._draw_rect(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "circle":
            self._draw_circle(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "triangle":
            self._draw_triangle(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "text":
            pos = cmd.get("pos", [0, 0])
            draw_list.add_text(
                ImVec2(ox + pos[0], oy + pos[1]), color, cmd.get("text", "")
            )
        elif cmd_type == "polyline":
            self._draw_polyline(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "bezier_cubic":
            self._draw_bezier(draw_list, cmd, color, thickness, ox, oy)

    def _draw_rect(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        mn = cmd.get("min", [0, 0])
        mx = cmd.get("max", [0, 0])
        rounding: float = cmd.get("rounding", 0.0)
        if cmd.get("filled", False):
            dl.add_rect_filled(
                ImVec2(ox + mn[0], oy + mn[1]),
                ImVec2(ox + mx[0], oy + mx[1]),
                color,
                rounding,
            )
        else:
            dl.add_rect(
                ImVec2(ox + mn[0], oy + mn[1]),
                ImVec2(ox + mx[0], oy + mx[1]),
                color,
                rounding,
                0,
                thickness,
            )

    def _draw_circle(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        center = cmd.get("center", [0, 0])
        radius: float = cmd.get("radius", 10)
        if cmd.get("filled", False):
            dl.add_circle_filled(ImVec2(ox + center[0], oy + center[1]), radius, color)
        else:
            dl.add_circle(
                ImVec2(ox + center[0], oy + center[1]),
                radius,
                color,
                0,
                thickness,
            )

    def _draw_triangle(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        p1 = cmd["p1"]
        p2 = cmd["p2"]
        p3 = cmd["p3"]
        if cmd.get("filled", False):
            dl.add_triangle_filled(
                ImVec2(ox + p1[0], oy + p1[1]),
                ImVec2(ox + p2[0], oy + p2[1]),
                ImVec2(ox + p3[0], oy + p3[1]),
                color,
            )
        else:
            dl.add_triangle(
                ImVec2(ox + p1[0], oy + p1[1]),
                ImVec2(ox + p2[0], oy + p2[1]),
                ImVec2(ox + p3[0], oy + p3[1]),
                color,
                thickness,
            )

    def _draw_polyline(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        im_draw_flags_closed = 1
        points_raw: list[list[float]] = cmd.get("points", [])
        closed: bool = cmd.get("closed", False)
        points = [ImVec2(ox + p[0], oy + p[1]) for p in points_raw]
        if len(points) >= 2:
            flags = im_draw_flags_closed if closed else 0
            dl.add_polyline(points, color, flags, thickness)

    def _draw_bezier(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        p1, p2, p3, p4 = cmd["p1"], cmd["p2"], cmd["p3"], cmd["p4"]
        dl.add_bezier_cubic(
            ImVec2(ox + p1[0], oy + p1[1]),
            ImVec2(ox + p2[0], oy + p2[1]),
            ImVec2(ox + p3[0], oy + p3[1]),
            ImVec2(ox + p4[0], oy + p4[1]),
            color,
            thickness,
        )

    # -- event flushing ----------------------------------------------------

    def _flush_events(self) -> None:
        if not self._event_queue:
            return
        if self._clients:
            for event in self._event_queue:
                for client in list(self._clients):
                    self._send_to_client(client, event)
        self._event_queue.clear()
