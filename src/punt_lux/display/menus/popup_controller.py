"""PopupController — what presses and releases on the title-bar glyphs do to the popup.

A click is a press and the release that follows it, so a release may act only
for the press that began on the same glyph. The controller holds the one press
in flight, from its edge until a release settles it, and lets only the frame
whose glyph it began on claim it. Without that a press that became a window
move, or a frame that vanished or was minimized mid-press, would leave a stale
answer for whichever glyph is released over next.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
    from punt_lux.display.menus.glyph_reading import GlyphReading
    from punt_lux.display.menus.open_popup import OpenFrame
    from punt_lux.display.menus.owner_rows import OwnerRows

__all__ = ["GlyphPress", "PopupController"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GlyphPress:
    """A press on one frame's glyph, and whether its popup was open when it fell."""

    frame: OpenFrame
    was_open: bool


@final
class PopupController:
    """Opens, closes, and refreshes the popup for the clicks the glyphs report."""

    _popup: FrameInfoPopup
    _rows: OwnerRows
    _press: GlyphPress | None
    _is_released: bool
    __slots__ = ("_is_released", "_popup", "_press", "_rows")

    def __new__(cls, popup: FrameInfoPopup, rows: OwnerRows) -> Self:
        self = super().__new__(cls)
        self._popup = popup
        self._rows = rows
        self._press = None
        self._is_released = False
        return self

    def observe(self, reading: GlyphReading, frame: OpenFrame) -> None:
        """Apply what one frame's glyph saw: a press begins, a click may toggle."""
        if reading.pressed:
            # Found open at the press: ImGui shuts the popup on a press outside
            # it, so by the release only the press tells a toggle-close.
            self._press = GlyphPress(frame, self._popup.is_open_for(frame))
        if reading.released:
            self._is_released = True
        if reading.clicked:
            self._click(frame, reading.anchor)

    def end_frame(self, *, is_released: bool) -> None:
        """Forget the press once any glyph saw its release, or the mouse did.

        A release over no glyph, or while the pressed frame was not drawn at all,
        still ends the press: only the mouse itself, not a glyph, can say so.
        """
        if self._is_released or is_released:
            self._press = None
        self._is_released = False

    def refresh_rows(self) -> None:
        """Re-read the open popup's facts, which may have arrived since it opened."""
        open_frame = self._popup.open_frame
        if open_frame is not None:
            self._popup.replace_rows(self._rows.for_refresh(open_frame))

    def _click(self, frame: OpenFrame, anchor: tuple[float, float]) -> None:
        """Toggle the popup for the press this release completes, if it has one."""
        press = self._press
        if press is None or press.frame != frame:
            logger.debug(
                "glyph release for %s ignored: its press began elsewhere", frame
            )
            return
        self._press = None
        if not press.was_open:
            self._popup.open_for(frame, self._rows.for_open(frame), anchor)
        elif self._popup.is_open_for(frame):
            # ImGui may have shut it on the press already: then nothing to close.
            self._popup.request_close()
