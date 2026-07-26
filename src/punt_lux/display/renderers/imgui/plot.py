# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""ImGuiPlotRenderer — Renderer-Protocol adapter for ``PlotElement``.

A display-only leaf that paints a 2D chart through ImPlot: axis setup and the
per-series line / scatter / bar dispatch, keyed so labels and titles render
verbatim while every item and plot still gets a distinct ImGui id. This migration
moves *where* the paint lives (the ABC leaf path, fork-don't-mix) and *who*
validates a series (the Hub, via ``PlotSeries``/``PlotElement.validate``), not how
ImPlot is driven. A typed ``PlotSeries`` carries a string label, so the label
``TypeError`` that used to fault mid-render is now impossible past decode; the
live defense-in-depth is the ragged-series skip, which drops a series whose
``x``/``y`` lengths differ (a shape the Hub's ``validate`` already rejects) rather
than handing ImPlot mismatched arrays. ``LeafRenderer`` adds the shared tooltip
pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import numpy as np
from imgui_bundle import ImVec2, imgui, implot

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.plot import PlotElement

if TYPE_CHECKING:
    from typing import Any

    from punt_lux.protocol.elements.plot_series import PlotSeries

__all__ = ["ImGuiPlotRenderer"]


@final
class ImGuiPlotRenderer(LeafRenderer[PlotElement]):
    """Paint a PlotElement's axes and every series + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the plot frame, axes, and every series within it."""
        elem = self._elem
        # An anonymous element (id == "") would push an empty scope, colliding
        # two same-title plots; fall back to object identity, stable within a
        # scene generation, so anonymous plots render collision-free.
        imgui.push_id(elem.id or f"anon-{id(elem)}")
        try:
            if implot.begin_plot(elem.title, ImVec2(elem.width, elem.height)):
                try:
                    if elem.x_label or elem.y_label:
                        implot.setup_axes(elem.x_label or "", elem.y_label or "")
                    for index, series in enumerate(elem.series):
                        self._plot_series(series, index)
                finally:
                    implot.end_plot()
        finally:
            imgui.pop_id()

    @staticmethod
    def _plot_series(series: PlotSeries, index: int) -> None:
        """Plot one series (line / scatter / bar) from its typed coordinates.

        Skips an empty or ragged series so ImPlot never receives mismatched
        arrays — defense-in-depth for a shape the Hub's ``validate`` rejects.
        """
        x_data = np.array(series.x, dtype=np.float64)
        y_data = np.array(series.y, dtype=np.float64)
        if len(x_data) == 0 or len(y_data) == 0 or series.is_ragged:
            return
        imgui.push_id(index)
        try:
            ImGuiPlotRenderer._draw(series.series_type, series.label, x_data, y_data)
        finally:
            imgui.pop_id()

    @staticmethod
    def _draw(series_type: str, label: str, x_data: Any, y_data: Any) -> None:
        """Issue the ImPlot call for one series type with the raw label."""
        if series_type == "line":
            implot.plot_line(label, x_data, y_data)
        elif series_type == "scatter":
            implot.plot_scatter(label, x_data, y_data)
        elif series_type == "bar":
            try:
                implot.plot_bars(label, x_data, y_data, 0.67)
            except TypeError:
                implot.plot_bars(label, y_data, 0.67)
