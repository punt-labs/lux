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
from typing import TYPE_CHECKING, Any

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
    ClearMessage,
    FrameReader,
    InteractionMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    SceneMessage,
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
# Display server
# ---------------------------------------------------------------------------


class DisplayServer:
    """ImGui display server with non-blocking Unix socket IPC."""

    def __init__(self, socket_path: str | None = None) -> None:
        self._socket_path = Path(socket_path or str(default_socket_path()))
        self._server_sock: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._readers: dict[int, FrameReader] = {}  # fd -> reader
        self._current_scene: SceneMessage | None = None
        self._event_queue: list[InteractionMessage] = []
        self._textures = TextureCache()

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
            conn, _ = self._server_sock.accept()
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
        except (ConnectionError, OSError):
            self._remove_client(sock)
        except ValueError:
            logger.warning("Malformed message from fd %d, disconnecting", sock.fileno())
            self._remove_client(sock)

    def _remove_client(self, sock: socket.socket) -> None:
        fd = sock.fileno()
        if sock in self._clients:
            self._clients.remove(sock)
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
            self._send_to_client(sock, AckMessage(scene_id=msg.id, ts=time.time()))
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
            elif patch.set:
                elem = elements[idx]
                for k, v in patch.set.items():
                    if k in ("id", "kind"):
                        continue
                    if hasattr(elem, k):
                        setattr(elem, k, v)

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

    def _render_element(self, elem: Element) -> None:
        kind: str = elem.kind  # widen from Literal to str for extensibility
        if kind == "text":
            self._render_text(elem)
        elif kind == "button":
            self._render_button(elem)
        elif kind == "separator":
            self._render_separator()
        elif kind == "image":
            self._render_image(elem)
        else:
            from imgui_bundle import imgui

            imgui.text(f"[unsupported element: {kind}]")

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

    def _render_separator(self) -> None:
        from imgui_bundle import imgui

        imgui.separator()

    def _render_image(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        img: Any = elem
        path: str | None = img.path
        width: int = img.width or 200
        height: int = img.height or 150

        tex_id = self._textures.get_or_load(path) if path else None
        if tex_id is not None:
            imgui.image(imgui.ImTextureRef(tex_id), ImVec2(width, height))
        else:
            alt: str = img.alt or path or "(image)"
            imgui.text(f"[{alt}]")

    # -- event flushing ----------------------------------------------------

    def _flush_events(self) -> None:
        if not self._event_queue:
            return
        if self._clients:
            for event in self._event_queue:
                for client in list(self._clients):
                    self._send_to_client(client, event)
        self._event_queue.clear()
