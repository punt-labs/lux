"""DisplayControlOperations — the display-fact reads and writes, all proxied.

The Hub cannot own an ImGui theme, a window's opacity, a GPU backend string, a
framebuffer capture, or a frame's transient minimize state. These operations
reach the running display over luxd's one connection through the injected
:class:`DisplayPort`. The caller still enters through a Hub operation, so there
is one code path; the reach-around that is gone is a tool or a command-line tool
talking to the display directly.

Two return shapes live here. The getters (``get_display_info``, ``get_theme``,
``get_window_settings``) answer with a typed result whose fields are the record,
and screenshot and ping answer with their own typed results. The setters
(``set_theme``, ``set_window_settings``, ``set_frame_state``) succeed with a
:class:`DisplayAck` the adapter formats back to the exact legacy status line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import DisplayAck, FrameStatePatch
from punt_lux.operations.models.theme import SetThemeRequest, ThemeState
from punt_lux.operations.models.window import WindowSettings, WindowSettingsPatch

if TYPE_CHECKING:
    from collections.abc import Mapping

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
            return OpError(code="rejected", reason="screenshot reply carried no path")
        return Screenshot(path=path)

    def ping(self, *, now: float) -> Pong | OpError:
        """Round-trip a ping and return the elapsed time."""
        payload = self._port.ping(now=now).resolve()
        if isinstance(payload, OpError):
            return payload
        rtt = payload.get("rtt_seconds")
        if not isinstance(rtt, int | float):
            return OpError(code="rejected", reason="ping reply carried no rtt")
        return Pong(rtt_seconds=float(rtt))

    # -- setters: DisplayAck the adapter formats to a legacy string --------

    def set_theme(self, request: SetThemeRequest | OpError) -> DisplayAck | OpError:
        """Switch the display theme, or pass the parse error through."""
        if isinstance(request, OpError):
            return request
        return self._write("set_theme", {"theme": request.theme})

    def set_window_settings(
        self, patch: WindowSettingsPatch | OpError
    ) -> DisplayAck | OpError:
        """Change the provided window settings, or pass the parse error through."""
        if isinstance(patch, OpError):
            return patch
        provided = patch.provided()
        if not provided:
            return OpError(code="invalid_request", reason="no settings provided")
        return self._write("set_window_settings", provided)

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch | OpError
    ) -> DisplayAck | OpError:
        """Change a frame's minimize state, or pass the parse error through."""
        if isinstance(patch, OpError):
            return patch
        params: dict[str, object] = {"frame_id": frame_id}
        if patch.minimized is not None:
            params["minimized"] = patch.minimized
        return self._write("set_frame_state", params)

    # -- shared proxy plumbing ---------------------------------------------

    def _write(self, method: str, params: Mapping[str, object]) -> DisplayAck | OpError:
        """Proxy a display write and wrap its reply as a formattable ack."""
        payload = self._port.query(method, params).resolve()
        if isinstance(payload, OpError):
            return payload
        return DisplayAck(payload=dict(payload))
