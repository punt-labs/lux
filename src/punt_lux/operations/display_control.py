"""DisplayControlOperations — the display-fact reads and writes, all proxied.

The Hub cannot own an ImGui theme, a window's opacity, a GPU backend string, a
framebuffer capture, or a frame's transient minimize state. These operations
reach the running display over luxd's one connection through the injected
:class:`DisplayPort`. The caller still enters through a Hub operation, so there
is one code path; the reach-around that is gone is a tool or a command-line tool
talking to the display directly.

Every operation answers with a typed result. The getters (``get_display_info``,
``get_theme``, ``get_window_settings``), the probes (``screenshot``, ``ping``),
and the setters (``set_theme`` → :class:`ThemeState`, ``set_window_settings`` →
:class:`WindowSettings`, ``set_frame_state`` → :class:`Ok`) all narrow the
display's reply into their result type; a reply the type does not recognize is
an ``OpError(rejected)``, never a fabricated success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import FrameStateAck, FrameStatePatch
from punt_lux.operations.models.menu_results import Ok
from punt_lux.operations.models.theme import SetThemeRequest, ThemeState
from punt_lux.operations.models.window import WindowSettings, WindowSettingsPatch

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort

__all__ = ["DisplayControlOperations"]


@final
class DisplayControlOperations:
    """Read and write display-process facts over luxd's one connection."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    # -- getters: typed records --------------------------------------------

    def get_display_info(self) -> DisplayInfo | OpError:
        """Return the display's backend, geometry, frame rate, and identity."""
        payload = self._port.query("get_display_info", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        return DisplayInfo.from_payload(payload)

    def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        payload = self._port.query("get_theme", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        return ThemeState.from_payload(payload)

    def get_window_settings(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        payload = self._port.query("get_window_settings", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        return WindowSettings.from_payload(payload)

    def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer and return the image path."""
        payload = self._port.query("screenshot", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        path = payload.get("path")
        if not isinstance(path, str):
            return OpError(code="fault", reason="screenshot reply carried no path")
        return Screenshot(path=path)

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a ping bounded by ``wait`` seconds; return the elapsed time.

        ``wait`` of ``None`` (the default) uses the connection's standing budget,
        so an MCP caller keeps its unchanged behavior.
        """
        payload = self._port.ping(wait).resolve()
        if isinstance(payload, OpError):
            return payload
        rtt = payload.get("rtt_seconds")
        if not isinstance(rtt, int | float):
            return OpError(code="fault", reason="ping reply carried no rtt")
        return Pong(rtt_seconds=float(rtt))

    # -- setters: narrow the reply into the write's own result type --------

    def set_theme(self, request: SetThemeRequest | OpError) -> ThemeState | OpError:
        """Switch the display theme and return the new theme state."""
        if isinstance(request, OpError):
            return request
        payload = self._port.query("set_theme", {"theme": request.theme}).resolve()
        if isinstance(payload, OpError):
            return payload
        return ThemeState.from_payload(payload)

    def set_window_settings(
        self, patch: WindowSettingsPatch | OpError
    ) -> WindowSettings | OpError:
        """Change the provided window settings and return the new settings."""
        if isinstance(patch, OpError):
            return patch
        provided = patch.provided()
        if not provided:
            return OpError(code="invalid_request", reason="no settings provided")
        payload = self._port.query("set_window_settings", provided).resolve()
        if isinstance(payload, OpError):
            return payload
        return WindowSettings.from_payload(payload)

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch | OpError
    ) -> Ok | OpError:
        """Change a frame's minimize state; an empty change is a caller mistake."""
        if isinstance(patch, OpError):
            return patch
        provided = patch.provided()
        if not provided:
            return OpError(code="invalid_request", reason="no frame state provided")
        payload = self._port.query(
            "set_frame_state", {"frame_id": frame_id, **provided}
        ).resolve()
        if isinstance(payload, OpError):
            return payload
        ack = FrameStateAck.from_reply(payload)
        if isinstance(ack, OpError):
            return ack
        if ack.frame_id != frame_id:
            reason = f"set_frame_state acknowledged {ack.frame_id!r}, not {frame_id!r}"
            return OpError(code="fault", reason=reason)
        return Ok()
