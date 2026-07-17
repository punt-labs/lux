# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render a ``PlotElement`` — a 2D chart of one or more data series.

Owns the whole plot paint surface: axis setup and the per-series line /
scatter / bar dispatch. Split out of ``ElementRenderer`` so the general
element dispatch and the plot subsystem each stay one responsibility
(PY-IC-6). A series carries no Lux state, so this renderer holds none —
it paints deterministically from the wire element.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

import numpy as np
from imgui_bundle import ImVec2, implot

if TYPE_CHECKING:
    from punt_lux.protocol.elements.plot_element import PlotElement

__all__ = ["PlotRenderer"]


@final
class PlotRenderer:
    """Paint a plot element and each of its data series."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: PlotElement) -> None:
        """Paint the plot frame, axes, and every series within it."""
        title = elem.title
        plot_title = title if "##" in title else f"{title}##{elem.id}"

        if implot.begin_plot(plot_title, ImVec2(elem.width, elem.height)):
            if elem.x_label or elem.y_label:
                implot.setup_axes(elem.x_label or "", elem.y_label or "")
            for series in elem.series:
                self._plot_series(series)
            implot.end_plot()

    @staticmethod
    def _plot_series(series: dict[str, Any]) -> None:
        """Plot one series (line / scatter / bar) from its wire mapping."""
        x_data = np.array(series.get("x", []), dtype=np.float64)
        y_data = np.array(series.get("y", []), dtype=np.float64)
        if len(x_data) == 0 or len(y_data) == 0:
            return

        label: str = series.get("label", "data")
        s_type: str = series.get("type", "line")
        if s_type == "line":
            implot.plot_line(label, x_data, y_data)
        elif s_type == "scatter":
            implot.plot_scatter(label, x_data, y_data)
        elif s_type == "bar":
            try:
                implot.plot_bars(label, x_data, y_data, 0.67)
            except TypeError:
                implot.plot_bars(label, y_data, 0.67)
