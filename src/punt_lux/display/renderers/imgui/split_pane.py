# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiSplitPaneRenderer — the ImGui adapter for a draggable two-pane split.

Renders a ``SplitPaneElement``'s two children in ``begin_child`` regions with an
``imgui_internal.splitter_behavior`` grab between them. A drag reallocates the
heights and writes the proportion back to the Display-local ``SplitRatioStore``
(per scene, no Hub round-trip); the top fraction is read each frame, defaulting to
``default_ratio``. Both panes clamp to a usable floor so neither collapses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.split_ratio_store import SplitRatioStore

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.split_pane import SplitPaneElement

__all__ = ["ImGuiSplitPaneRenderer"]

# Height of the draggable grab band, in pixels.
_DIVIDER_THICKNESS = 8.0
# Usable-height floors for each pane, in text lines.
_MIN_GRID_ROWS = 4
_MIN_DETAIL_LINES = 3


@final
class ImGuiSplitPaneRenderer:
    """Paint a SplitPaneElement: two child regions and a draggable divider."""

    _elem: SplitPaneElement
    _factory: ImGuiRendererFactory
    _store: SplitRatioStore
    _top_height: float
    _bottom_height: float
    __slots__ = ("_bottom_height", "_elem", "_factory", "_store", "_top_height")

    def __new__(cls, elem: SplitPaneElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        self._store = SplitRatioStore(factory.widget_state, elem.id)
        self._top_height = 0.0
        self._bottom_height = 0.0
        return self

    def begin(self) -> bool:
        """Open nothing of its own — the panes open their own child regions."""
        return True

    def paint(self) -> None:
        """No-op — a split's only body is its two panes."""

    def end(self, *, opened: bool) -> None:
        """Apply the shared hover tooltip after the panes have painted."""
        _ = opened
        self._factory.apply_tooltip(self._elem)

    def open_top(self) -> None:
        """Size the two panes from the stored ratio and open the top region."""
        avail = imgui.get_content_region_avail()
        usable = max(avail.y - _DIVIDER_THICKNESS, self._floor_total())
        top = self._store.ratio(self._elem.default_ratio) * usable
        self._top_height = self._clamp_top(top, usable)
        self._bottom_height = usable - self._top_height
        imgui.begin_child(
            f"{self._elem.id}##split-top", imgui.ImVec2(0.0, self._top_height)
        )

    def close_top(self) -> None:
        """Close the top pane's child region."""
        imgui.end_child()

    def draw_divider(self) -> None:
        """Draw the grab, apply a drag to the heights, and persist the ratio."""
        pos = imgui.get_cursor_screen_pos()
        width = imgui.get_content_region_avail().x
        held, top, bottom = imgui.internal.splitter_behavior(
            imgui.internal.ImRect(
                pos.x, pos.y, pos.x + width, pos.y + _DIVIDER_THICKNESS
            ),
            imgui.get_id(f"{self._elem.id}##split-divider"),
            imgui.internal.Axis.y,
            self._top_height,
            self._bottom_height,
            self._min_top(),
            self._min_bottom(),
        )
        self._top_height, self._bottom_height = top, bottom
        if held and top + bottom > 0.0:
            self._store.set_ratio(top / (top + bottom))
        self._paint_grab(pos, width)
        imgui.dummy(imgui.ImVec2(width, _DIVIDER_THICKNESS))

    def open_bottom(self) -> None:
        """Open the bottom pane's child region at the remaining height."""
        imgui.begin_child(
            f"{self._elem.id}##split-bottom", imgui.ImVec2(0.0, self._bottom_height)
        )

    def close_bottom(self) -> None:
        """Close the bottom pane's child region."""
        imgui.end_child()

    # -- geometry helpers ---------------------------------------------------

    def _paint_grab(self, pos: imgui.ImVec2, width: float) -> None:
        """Draw a separator-coloured bar centred in the grab band.

        Packed via the vec4 helpers, not the ambiguous two-overload get_color_u32.
        """
        style_color = imgui.get_style_color_vec4(int(imgui.Col_.separator.value))
        color = imgui.color_convert_float4_to_u32(style_color)
        middle = pos.y + _DIVIDER_THICKNESS * 0.5
        imgui.get_window_draw_list().add_rect_filled(
            imgui.ImVec2(pos.x, middle - 1.0),
            imgui.ImVec2(pos.x + width, middle + 1.0),
            color,
        )

    def _clamp_top(self, top: float, usable: float) -> float:
        """Confine the top height so neither pane falls below its floor."""
        ceiling = max(usable - self._min_bottom(), self._min_top())
        return min(max(top, self._min_top()), ceiling)

    def _floor_total(self) -> float:
        """Return the combined pane floor — the least usable split height."""
        return self._min_top() + self._min_bottom()

    def _min_top(self) -> float:
        """Return the grid pane's floor in pixels."""
        return _MIN_GRID_ROWS * imgui.get_text_line_height_with_spacing()

    def _min_bottom(self) -> float:
        """Return the detail pane's floor in pixels."""
        return _MIN_DETAIL_LINES * imgui.get_text_line_height_with_spacing()
