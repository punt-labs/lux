"""FrameInfoButton — the title-bar info glyph that owns and drives its popup.

The glyph sits just left of a frame's native close x. Clicking it opens the
:class:`~punt_lux.display.menus.frame_info_popup.FrameInfoPopup` the button
owns, anchored at the glyph, showing the frame's owning-connection facts; a
second click while that popup is still open dismisses it, so the glyph toggles
rather than reopening what is already shown. The button owns the popup because
they are one affordance -- the glyph is the popup's only opener -- so the
render loop holds just the button and reaches the popup through :attr:`popup`
to render it at the popup-layer root scope. Painting and click detection live
in :class:`~punt_lux.display.menus.frame_info_glyph.FrameInfoGlyph`.

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
    """The title-bar info glyph and the popup it toggles.

    Facts are read from ``facts_for`` by ``(hub, frame_id)``, not from the
    frame itself -- the snapshot lives in the ``OwnerFactsStore``
    ``SceneReplica`` owns, not on the ``Frame`` aggregate root.
    """

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

    @property
    def popup(self) -> FrameInfoPopup:
        """The popup this glyph opens; the render loop renders it at root scope."""
        return self._popup

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw the glyph for ``frame``; a click opens or toggles its popup."""
        self._toggle.render(frame, imgui)
