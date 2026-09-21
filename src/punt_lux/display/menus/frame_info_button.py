"""FrameInfoButton — the title-bar info glyph that owns and drives its popup.

The glyph sits just left of a frame's native close x. Clicking it opens the
:class:`~punt_lux.display.menus.frame_info_popup.FrameInfoPopup` the button
owns, anchored at the glyph, showing the frame's owning-connection facts; a
second click while that popup is still open dismisses it, so the glyph toggles
rather than reopening what is already shown. The button owns the popup because
they are one affordance -- the glyph is the popup's only opener -- so the
render loop holds just the button and reaches the popup through :attr:`popup`
to render it at the popup-layer root scope.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from imgui_bundle import ImVec2

from punt_lux.display.menus.frame_info_popup import FrameInfoPopup

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoButton"]

# What the popup shows when the Hub has no facts for the frame's owner yet --
# untracked or the owning connection has already departed. Distinguished from
# a resolved-but-genuinely-empty result so a click is never a silent no-op.
_UNKNOWN_OWNER_ROWS: tuple[tuple[str, str], ...] = (("Owner", "unknown"),)


@final
class FrameInfoButton:
    """The title-bar info glyph, positioned just left of the native close x.

    Facts are read from ``facts_for`` by ``(hub, frame_id)``, not from the
    frame itself -- the snapshot lives in the ``OwnerFactsStore``
    ``SceneReplica`` owns, not on the ``Frame`` aggregate root.

    Painted on the foreground draw list, not as a normal ImGui item: a title
    bar sits outside the window's content-area clip rect, which would silently
    cull an item placed there (``small_button`` included) before it drew. The
    foreground draw list has no such clip rect (as ``DockPill`` relies on too),
    so this paints the glyph by hand and hit-tests the raw mouse position.
    """

    # ASCII "i": primary font + fallback lack U+24D8 "ⓘ", which renders as tofu.
    _LABEL = "i"
    _GAP = 4.0
    _SCALE = 0.625  # glyph diameter as a fraction of the title-bar band

    _popup: FrameInfoPopup
    _facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None]
    __slots__ = ("_facts_for", "_popup")

    def __new__(
        cls,
        frame_for: Callable[[str, HubId], Frame | None],
        facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._popup = FrameInfoPopup(frame_for)
        self._facts_for = facts_for
        return self

    @property
    def popup(self) -> FrameInfoPopup:
        """The popup this glyph opens; the render loop renders it at root scope."""
        return self._popup

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw the glyph for ``frame``; a click opens or toggles its popup."""
        pos = imgui.get_window_pos()
        size = imgui.get_window_size()
        glyph = (band := imgui.get_frame_height()) * self._SCALE
        high = ImVec2(pos.x + size.x - band - self._GAP, pos.y + (band + glyph) / 2)
        low = ImVec2(high.x - glyph, high.y - glyph)
        hovered = self._paint(imgui, low, high)
        if hovered and imgui.is_mouse_clicked(imgui.MouseButton_.left):
            self._toggle(frame, (low.x, low.y))

    def _toggle(self, frame: Frame, anchor: tuple[float, float]) -> None:
        """Dismiss the popup if it already shows this frame, else open it."""
        if self._popup.is_open_for(frame.frame_id, frame.hub):
            self._popup.request_close()
            return
        resolved = self._facts_for(frame.frame_id, frame.hub)
        rows = resolved if resolved is not None else _UNKNOWN_OWNER_ROWS
        self._popup.open_for(frame.frame_id, frame.hub, rows, anchor)

    @staticmethod
    def _hovered(imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Whether the mouse sits inside the glyph's rect -- raw geometry, since
        the glyph is not a real ImGui item for ImGui to hover."""
        mouse = imgui.get_mouse_pos()
        return bool(low.x <= mouse.x <= high.x and low.y <= mouse.y <= high.y)

    def _paint(self, imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Fill the glyph's rect and center its label; return whether hovered.

        Reports its own hover state like an ImGui widget returns its result, so
        the caller reads it once for the click test.
        """
        hovered = self._hovered(imgui, low, high)
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()
        fill = imgui.Col_.button_hovered if hovered else imgui.Col_.button
        rounding = (high.x - low.x) * 0.5
        draw.add_rect_filled(
            low, high, imgui.get_color_u32(style.color_(fill)), rounding
        )
        text_size = imgui.calc_text_size(self._LABEL)
        text_pos = ImVec2(
            low.x + (high.x - low.x - text_size.x) * 0.5,
            low.y + (high.y - low.y - text_size.y) * 0.5,
        )
        draw.add_text(
            text_pos, imgui.get_color_u32(style.color_(imgui.Col_.text)), self._LABEL
        )
        return hovered
