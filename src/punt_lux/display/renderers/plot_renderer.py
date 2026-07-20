# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render a ``PlotElement`` — a 2D chart of one or more data series.

Owns the whole plot paint surface: axis setup and the per-series line /
scatter / bar dispatch. Split out of ``ElementRenderer`` so the general
element dispatch and the plot subsystem each stay one responsibility
(PY-IC-6). A series carries no Lux state, so this renderer holds none —
it paints deterministically from the wire element.

ImPlot keys each item by its label and each plot by its title, both hashed
against the live ImGui ID stack. Two series that share a label — including
the label-less default "data" — would land in one item slot and flicker, and
two plots that share a title would collide. The renderer scopes each plot by
the element id and each series by its index with ``imgui.push_id`` instead of
mangling the visible strings, so labels and titles render verbatim (a label
such as "C#" is not corrupted by an appended delimiter) while every item and
plot still gets a distinct ImGui id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

import numpy as np
from imgui_bundle import ImVec2, imgui, implot

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
        # Reject a malformed element before opening any ImGui/ImPlot state, so
        # the designed rejection never leaves the render stack half-open. The
        # nested finally below is structural insurance for any other in-body
        # failure (a raising setup_axes or plot call).
        labels = self._series_labels(elem.series)
        # An anonymous element (id == "") would push an empty scope, so two
        # anonymous same-title plots would collide on one ImPlot plot id and
        # flicker. Fall back to the element's object identity, which is stable
        # across frames within one scene generation, so anonymous plots render
        # collision-free. The tradeoff: on a whole-scene re-push the elements
        # are rebuilt, the identity changes, and an anonymous plot loses its
        # ImPlot view state (zoom, legend toggles) — accepted, since the
        # alternative is the collision.
        imgui.push_id(elem.id or f"anon-{id(elem)}")
        try:
            if implot.begin_plot(elem.title, ImVec2(elem.width, elem.height)):
                try:
                    if elem.x_label or elem.y_label:
                        implot.setup_axes(elem.x_label or "", elem.y_label or "")
                    for index, series in enumerate(elem.series):
                        self._plot_series(series, labels[index], index)
                finally:
                    implot.end_plot()
        finally:
            imgui.pop_id()

    @staticmethod
    def _series_labels(series: list[dict[str, Any]]) -> list[str]:
        """Return each series' legend label, raising on the first non-str.

        The series mapping is unvalidated ``Any``; a label that is ``None`` or a
        number would render as "None"/"5", so the whole element is rejected
        before any drawing begins.
        """
        labels: list[str] = []
        for s in series:
            label = s.get("label", "data")
            if not isinstance(label, str):
                msg = f"series label must be a str, got {type(label).__name__}"
                raise TypeError(msg)
            labels.append(label)
        return labels

    @staticmethod
    def _plot_series(series: dict[str, Any], label: str, index: int) -> None:
        """Plot one series (line / scatter / bar) from its wire mapping."""
        x_data = np.array(series.get("x", []), dtype=np.float64)
        y_data = np.array(series.get("y", []), dtype=np.float64)
        if len(x_data) == 0 or len(y_data) == 0:
            return

        s_type: str = series.get("type", "line")
        imgui.push_id(index)
        try:
            PlotRenderer._emit(s_type, label, x_data, y_data)
        finally:
            imgui.pop_id()

    @staticmethod
    def _emit(s_type: str, label: str, x_data: Any, y_data: Any) -> None:
        """Issue the ImPlot call for one series type with the raw label."""
        if s_type == "line":
            implot.plot_line(label, x_data, y_data)
        elif s_type == "scatter":
            implot.plot_scatter(label, x_data, y_data)
        elif s_type == "bar":
            try:
                implot.plot_bars(label, x_data, y_data, 0.67)
            except TypeError:
                implot.plot_bars(label, y_data, 0.67)
