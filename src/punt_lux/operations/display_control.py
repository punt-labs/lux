"""DisplayControlOperations — the display-fact reads and writes, all proxied.

The Hub cannot own an ImGui theme, a window's opacity, a GPU backend string, or
where a frame sits --- on screen, docked, or put away by the user. These
operations reach the running display over luxd's one connection through the
injected :class:`DisplayPort`; the reach-around that is gone is a tool talking
to the display directly, so there is still one code path.

Every operation answers with a typed result: a reply the result type does not
recognize is an ``OpError(rejected)``, never a fabricated success. Frame
visibility (raising a frame) is never one of these operations at all — that
is a Display-local, user-gesture-only concern (DES-088); no client op reaches
around to move a frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.display_reply import DisplayReplied
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_frames import FrameStates
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import (
    FrameStateAck,
    FrameStatePatch,
)
from punt_lux.operations.models.menu_results import Ok
from punt_lux.operations.models.theme import ThemeState
from punt_lux.operations.models.window import WindowSettings

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
        reply = self._port.query("get_display_info", {})
        if isinstance(reply, DisplayReplied):
            return DisplayInfo.from_payload(
                {**reply.payload, "hub_connection_id": reply.connection}
            )
        return reply.resolve()

    def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        data = self._port.query("get_theme", {}).resolve()
        return data if isinstance(data, OpError) else ThemeState.from_payload(data)

    def get_window_settings(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        data = self._port.query("get_window_settings", {}).resolve()
        return data if isinstance(data, OpError) else WindowSettings.from_payload(data)

    def screenshot(self) -> Screenshot | OpError:
        """Capture the display's next painted frame to a PNG on the display host.

        The display answers this query one frame late, after the swap that paints
        it, so a bounded reply is the frame as presented. The path is on the
        display's host; a caller on another machine cannot open it.
        """
        payload = self._port.query("screenshot", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        path = payload.get("path")
        if not isinstance(path, str) or not path:
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
        data = self._port.query("list_scenes", {}).resolve()
        return data if isinstance(data, OpError) else FrameStates.from_payload(data)
