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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, final

import numpy as np
from imgui_bundle import ImVec2, implot

if TYPE_CHECKING:
    from punt_lux.protocol.elements.plot_element import PlotElement

__all__ = ["PlotRenderer"]


@final
@dataclass(frozen=True, slots=True)
class SeriesLabel:
    """The visible legend text and unique ImPlot item ID for one series.

    ImPlot keys every item by its label string, so two series sharing a
    label — including the label-less default "data" — land in one item
    slot and fight over it. The per-plot series index disambiguates the
    ID; "##" hides that suffix from the legend, so the text a viewer reads
    is unchanged. ImPlot scopes items per plot, so the index alone is
    unique within a plot — the element id need not be threaded in.
    """

    _text: str
    _index: int

    @property
    def visible(self) -> str:
        """Return the legend text a viewer sees (the part before "##")."""
        return self._text.split("##", 1)[0]

    @property
    def item_id(self) -> str:
        """Return the ImPlot item ID: the label with a hidden unique suffix."""
        return f"{self._text}##{self._index}"


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
            for index, series in enumerate(elem.series):
                self._plot_series(series, index)
            implot.end_plot()

    @staticmethod
    def _plot_series(series: dict[str, Any], index: int) -> None:
        """Plot one series (line / scatter / bar) from its wire mapping."""
        x_data = np.array(series.get("x", []), dtype=np.float64)
        y_data = np.array(series.get("y", []), dtype=np.float64)
        if len(x_data) == 0 or len(y_data) == 0:
            return

        item_id = SeriesLabel(series.get("label", "data"), index).item_id
        s_type: str = series.get("type", "line")
        if s_type == "line":
            implot.plot_line(item_id, x_data, y_data)
        elif s_type == "scatter":
            implot.plot_scatter(item_id, x_data, y_data)
        elif s_type == "bar":
            try:
                implot.plot_bars(item_id, x_data, y_data, 0.67)
            except TypeError:
                implot.plot_bars(item_id, y_data, 0.67)
