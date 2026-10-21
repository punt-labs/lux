"""FrameInfoToggle — the title-bar glyph, and what its clicks do to the popup.

A click closes the popup it found open, else opens it. "Found open" is read at
the *press*: a press outside the popup makes ImGui shut it on that very frame,
so by the release only the press tells a toggle-close from a fresh open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.frame_info_glyph import FrameInfoGlyph
from punt_lux.display.menus.owner_rows import OwnerRows

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoToggle"]


@final
class FrameInfoToggle:
    """Draw one frame's glyph and apply what the mouse did to it to the popup."""

    _glyph: FrameInfoGlyph
    _popup: FrameInfoPopup
    _rows: OwnerRows
    _was_open_at_press: bool
    __slots__ = ("_glyph", "_popup", "_rows", "_was_open_at_press")

    def __new__(
        cls,
        popup: FrameInfoPopup,
        facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._glyph = FrameInfoGlyph()
        self._popup = popup
        self._rows = OwnerRows(facts_for)
        self._was_open_at_press = False
        return self

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw ``frame``'s glyph, record a press, and act on a click."""
        reading = self._glyph.render(imgui)
        if reading.pressed:
            self._was_open_at_press = self._popup.is_open_for(frame.frame_id, frame.hub)
        if reading.clicked:
            self._toggle(frame, reading.anchor)

    def refresh_rows(self) -> None:
        """Re-read the open popup's facts, which may have arrived since it opened."""
        open_frame = self._popup.open_frame
        if open_frame is not None:
            self._popup.replace_rows(
                self._rows.for_refresh(open_frame.frame_id, open_frame.hub)
            )

    def _toggle(self, frame: Frame, anchor: tuple[float, float]) -> None:
        """Close the popup this click found open, else open it."""
        was_open, self._was_open_at_press = self._was_open_at_press, False
        if was_open:
            # ImGui may already have shut it on the press: nothing left to close.
            if self._popup.is_open_for(frame.frame_id, frame.hub):
                self._popup.request_close()
            return
        rows = self._rows.for_open(frame.frame_id, frame.hub)
        self._popup.open_for(frame.frame_id, frame.hub, rows, anchor)
