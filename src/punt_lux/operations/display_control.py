"""DisplayControlOperations — the display-fact reads and writes, all proxied.

The Hub cannot own an ImGui theme, a window's opacity, a GPU backend string, or
where a frame sits --- on screen, docked, or put away by the user. These
operations reach the running display over luxd's one connection through the
injected :class:`DisplayPort`; the reach-around that is gone is a tool talking
to the display directly, so there is still one code path.

Every operation answers with a typed result: a reply the result type does not
recognize is an ``OpError(rejected)``, never a fabricated success.
``screenshot`` is the lone operation that never reaches the display —
framebuffer capture is unsupported (DES-028), so it refuses up front. Frame
visibility (raising a frame) is never one of these operations at all — that
is a Display-local, user-gesture-only concern (DES-088); no client op reaches
around to move a frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_frames import FrameStates
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import (
    FrameStateAck,
    FrameStatePatch,
)
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
        """Refuse cleanly: framebuffer capture is unsupported (DES-028)."""
        return OpError(
            code="rejected",
            reason="screenshot capture is not supported by the display; see DES-028",
        )

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

    def list_frames(self) -> FrameStates | OpError:
        """Return every frame the display holds and where it is showing each one.

        The read that makes a closed frame observable from outside the display.
        Closing is a visibility and not an erasure (DES-088), so a frame the user
        shut is still here — a caller can no longer tell it from a frame that
        never existed by its absence, and this is where it learns the difference.

        Not a field on ``list_scenes``: that read is Hub-authoritative and never
        reaches around to the display, and where a window sits is not a fact the
        Hub has. Here it sits beside :meth:`set_frame_state`, the other
        operation over the same state.
        """
        payload = self._port.query("list_scenes", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        return FrameStates.from_payload(payload)
