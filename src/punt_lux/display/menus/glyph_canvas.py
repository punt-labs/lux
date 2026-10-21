"""GlyphCanvas — the ImGui a frame's title-bar glyph draws and hit-tests in.

A glyph is drawn inside its frame's window, so what stands in front of it is
the info popup's business as much as ImGui's: the canvas carries both, and the
frame the glyph belongs to.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.popup_cover import PopupCover

if TYPE_CHECKING:
    from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
    from punt_lux.display.replica.frame import Frame

__all__ = ["GlyphCanvas"]


@dataclass(frozen=True, slots=True)
class GlyphCanvas:
    """The ImGui handle, the glyph's frame, and the info popup's stance over it."""

    imgui: Any
    frame: OpenFrame
    popup: PopupCover

    @classmethod
    def over(cls, imgui: Any, popup: FrameInfoPopup, frame: Frame) -> Self:
        """Return the canvas of ``frame``'s glyph, with ``popup`` as it stands."""
        key = OpenFrame(frame.frame_id, frame.hub)
        cover = PopupCover(popup.window_id, is_for_frame=popup.is_open_for(key))
        return cls(imgui, key, cover)
