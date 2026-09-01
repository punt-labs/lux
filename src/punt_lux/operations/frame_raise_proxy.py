"""FrameRaiseProxy — bring a frame the display already knows to the front.

Where a window sits is not the Hub's to give (DES-088), so raising one is a
write proxied over the same connection :class:`FrameVisibilityProxy` reads
from -- a sibling, not a second job inside it: nothing that reads visibility
ever raises a frame, and nothing that raises a frame reads visibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_write import FrameRaise

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort

__all__ = ["FrameRaiseProxy"]


@final
class FrameRaiseProxy:
    """Bring a frame the display already knows -- by its own id -- to the front."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def raise_frame(self, frame_id: str) -> FrameRaise | OpError:
        """Bring ``frame_id`` -- already the display's own id -- to the front."""
        payload = self._port.query("raise_frame", {"frame_id": frame_id}).resolve()
        raised = (
            payload if isinstance(payload, OpError) else FrameRaise.from_reply(payload)
        )
        if isinstance(raised, OpError):
            return raised
        reason = f"raise_frame answered for {raised.frame_id!r}, not {frame_id!r}"
        return (
            raised
            if raised.frame_id == frame_id
            else OpError(code="fault", reason=reason)
        )
