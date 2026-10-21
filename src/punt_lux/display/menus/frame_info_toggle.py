"""FrameInfoToggle — draws one frame's title-bar glyph and feeds its mouse edges on.

A click closes the popup it found open, else opens it; the
:class:`~punt_lux.display.menus.popup_controller.PopupController` settles which.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.frame_info_glyph import FrameInfoGlyph
from punt_lux.display.menus.glyph_reading import GlyphReading
from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.owner_rows import OwnerRows
from punt_lux.display.menus.popup_controller import PopupController

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
    _controller: PopupController
    __slots__ = ("_controller", "_glyph")

    def __new__(
        cls,
        popup: FrameInfoPopup,
        facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._glyph = FrameInfoGlyph()
        self._controller = PopupController(popup, OwnerRows(facts_for))
        return self

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw ``frame``'s glyph and apply its press, release, and click."""
        reading = self._glyph.render(imgui)
        self._controller.observe(reading, OpenFrame(frame.frame_id, frame.hub))

    def end_frame(self, imgui: Any) -> None:
        """Close out the frame: a release anywhere ends the press in flight."""
        self._controller.end_frame(is_released=GlyphReading.is_release(imgui))

    def refresh_rows(self) -> None:
        """Re-read the open popup's facts, which may have arrived since it opened."""
        self._controller.refresh_rows()
