"""FrameInfoButton — the title-bar info glyph that owns and drives its popup.

Clicking the glyph opens the
:class:`~punt_lux.display.menus.frame_info_popup.FrameInfoPopup` the button owns,
anchored at the glyph with the frame's owning-connection facts; a second click
dismisses it. The glyph is the popup's only opener, so the render loop holds
just the button and renders the popup through :meth:`render_popup` at the
popup-layer root scope. The click logic lives in
:class:`~punt_lux.display.menus.frame_info_toggle.FrameInfoToggle`.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
from punt_lux.display.menus.frame_info_toggle import FrameInfoToggle

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoButton"]


@final
class FrameInfoButton:
    """The title-bar info glyph and the popup it toggles."""

    _popup: FrameInfoPopup
    _toggle: FrameInfoToggle
    __slots__ = ("_popup", "_toggle")

    def __new__(
        cls,
        frame_for: Callable[[str, HubId], Frame | None],
        facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._popup = FrameInfoPopup(frame_for)
        self._toggle = FrameInfoToggle(self._popup, facts_for)
        return self

    def render_popup(self, imgui: Any) -> None:
        """Render the popup at the popup-layer root scope, with fresh facts."""
        self._toggle.refresh_rows()
        self._popup.render(imgui)

    @property
    def popup(self) -> FrameInfoPopup:
        """The popup this glyph opens; exposed so tests can inspect it."""
        return self._popup

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw the glyph for ``frame``; a click opens or toggles its popup."""
        self._toggle.render(frame, imgui)
