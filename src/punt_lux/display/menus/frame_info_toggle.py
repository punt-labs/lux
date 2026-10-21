"""FrameInfoToggle — the title-bar glyph, and what its clicks do to the popup.

A click closes the popup it found open and otherwise opens it. "Found open"
is read at the *press*, not the release: a press outside the popup makes ImGui
shut it on that very frame, so by the release the popup reads closed whether
the press closed it or never found it open, and only the moment of the press
tells a toggle-close from a fresh open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.frame_info_glyph import FrameInfoGlyph

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoToggle"]

# What the popup shows when the Hub has no facts for the frame's owner yet --
# untracked or the owning connection has already departed. Distinguished from
# a resolved-but-genuinely-empty result so a click is never a silent no-op.
_UNKNOWN_OWNER_ROWS: tuple[tuple[str, str], ...] = (("Owner", "unknown"),)


@final
class FrameInfoToggle:
    """Draw one frame's glyph and apply what the mouse did to it to the popup."""

    _glyph: FrameInfoGlyph
    _popup: FrameInfoPopup
    _facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None]
    _was_open_at_press: bool
    __slots__ = ("_facts_for", "_glyph", "_popup", "_was_open_at_press")

    def __new__(
        cls,
        popup: FrameInfoPopup,
        facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._glyph = FrameInfoGlyph()
        self._popup = popup
        self._facts_for = facts_for
        self._was_open_at_press = False
        return self

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw ``frame``'s glyph, record a press, and act on a click."""
        reading = self._glyph.render(imgui)
        if reading.pressed:
            self._was_open_at_press = self._popup.is_open_for(frame.frame_id, frame.hub)
        if reading.clicked:
            self._toggle(frame, reading.anchor)

    def _toggle(self, frame: Frame, anchor: tuple[float, float]) -> None:
        """Close the popup this click found open, else open it."""
        was_open, self._was_open_at_press = self._was_open_at_press, False
        if was_open:
            # ImGui may already have shut it on the press; then there is no
            # dismissal left to request.
            if self._popup.is_open_for(frame.frame_id, frame.hub):
                self._popup.request_close()
            return
        resolved = self._facts_for(frame.frame_id, frame.hub)
        rows = resolved if resolved is not None else _UNKNOWN_OWNER_ROWS
        self._popup.open_for(frame.frame_id, frame.hub, rows, anchor)
