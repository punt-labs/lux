# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""ImGuiPlotRenderer — Renderer-Protocol adapter for ``PlotElement``.

A display-only leaf that paints a 2D chart through ImPlot: axis setup and the
per-series line / scatter / bar dispatch, keyed so labels and titles render
verbatim while every item and plot still gets a distinct ImGui id. This migration
moves *where* the paint lives (the ABC leaf path, fork-don't-mix) and *who*
validates a series (the Hub, via ``PlotSeries``/``PlotElement.validate``), not how
ImPlot is driven. A typed ``PlotSeries`` carries a string label, so the label
``TypeError`` that used to fault mid-render is now impossible past decode.

Two silent-failure guards make the remaining defense-in-depth visible rather than
quiet: a ragged series (a shape the Hub's ``validate`` already rejects) is skipped
*and logged*, so if the branch ever fires the Hub gap is traceable instead of
silently rendering partial data as complete; and bar drawing adapts once to the
installed ``implot.plot_bars`` signature (see ``_BarSeriesPlotter``) and warns when
a y-only binding cannot honor explicit x-coordinates. ``LeafRenderer`` adds the
shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

import numpy as np
from imgui_bundle import ImVec2, imgui, implot

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.plot import PlotElement

if TYPE_CHECKING:
    from typing import Any

    from punt_lux.protocol.elements.plot_series import PlotSeries

__all__ = ["ImGuiPlotRenderer"]

logger = logging.getLogger(__name__)


@final
class _BarSeriesPlotter:
    """Draw bar series, dispatching on the declared ``implot.plot_bars`` signature.

    imgui-bundle ships two plot_bars forms: explicit-x ``(label, xs, ys, bar_size)``
    and y-only ``(label, values, bar_size)``. Which is available is read once from
    the binding's own declared signature — *not* probed by catching a ``TypeError``,
    so a genuine ``TypeError`` (bad arrays) propagates on every call including the
    first instead of being masked into a silent y-only mis-render. On a y-only
    build, explicit x cannot be honored: a series carrying non-index x renders at
    0..n-1, so warn once rather than silently mispositioning the bars.
    """

    _takes_x: bool
    _warned: bool
    __slots__ = ("_takes_x", "_warned")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._takes_x = cls._binding_takes_explicit_x()
        self._warned = False
        return self

    @staticmethod
    def _binding_takes_explicit_x() -> bool:
        """Return whether the installed plot_bars declares an explicit-x overload.

        Reads ``implot.plot_bars.__doc__`` (``inspect.signature`` raises on the
        nanobind binding). An explicit-x overload declares two leading array
        parameters (``xs``, ``ys``) before ``bar_size``; the y-only overload
        declares one (``values``). Raises ``RuntimeError`` if the binding declares
        no parseable signature — a build problem to surface, not to guess around.
        """
        doc = implot.plot_bars.__doc__ or ""
        overloads = [
            ln for ln in doc.splitlines() if ln.lstrip().startswith("plot_bars(")
        ]
        if not overloads:
            msg = "cannot read implot.plot_bars signature from the installed binding"
            raise RuntimeError(msg)
        count = _BarSeriesPlotter._leading_array_count
        return any(count(line) >= 2 for line in overloads)

    @staticmethod
    def _leading_array_count(signature: str) -> int:
        """Count the leading ``ndarray`` params after ``label_id`` in one overload."""
        params = signature[signature.index("(") + 1 : signature.rindex(")")].split(",")
        count = 0
        for param in params[1:]:  # skip label_id
            if "ndarray" not in param:
                break
            count += 1
        return count

    def plot(self, label: str, x_data: Any, y_data: Any) -> None:
        """Draw one bar series, honoring explicit x where the binding supports it."""
        if self._takes_x:
            implot.plot_bars(label, x_data, y_data, 0.67)
        else:
            self._plot_y_only(label, x_data, y_data)

    def _plot_y_only(self, label: str, x_data: Any, y_data: Any) -> None:
        """Draw with the y-only signature, warning once if x carried real positions."""
        if not self._warned and not self._is_index_ramp(x_data, y_data):
            logger.warning(
                "implot.plot_bars on this imgui-bundle build takes no x argument; "
                "bar series %r with explicit x renders at indices 0..%d",
                label,
                len(y_data) - 1,
            )
            self._warned = True
        implot.plot_bars(label, y_data, 0.67)

    @staticmethod
    def _is_index_ramp(x_data: Any, y_data: Any) -> bool:
        """Return whether x is the trivial 0..n-1 ramp the y-only form implies."""
        ramp = np.arange(len(y_data), dtype=np.float64)
        return bool(np.array_equal(x_data, ramp))


# One plotter per process: the plot_bars signature is a property of the installed
# imgui-bundle binding, determined once and shared across every plot rendered.
_BARS = _BarSeriesPlotter()


@final
class ImGuiPlotRenderer(LeafRenderer[PlotElement]):
    """Paint a PlotElement's axes and every series + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the plot under a per-element id scope so titles never collide."""
        elem = self._elem
        # An anonymous element (id == "") would push an empty scope, colliding
        # two same-title plots; fall back to object identity, stable within a
        # scene generation, so anonymous plots render collision-free.
        imgui.push_id(elem.id or f"anon-{id(elem)}")
        try:
            self._paint_plot(elem)
        finally:
            imgui.pop_id()

    def _paint_plot(self, elem: PlotElement) -> None:
        """Open the ImPlot frame, set the axes, and paint every series."""
        if not implot.begin_plot(elem.title, ImVec2(elem.width, elem.height)):
            return
        try:
            if elem.x_label or elem.y_label:
                implot.setup_axes(elem.x_label or "", elem.y_label or "")
            for index, series in enumerate(elem.series):
                self._plot_series(series, index)
        finally:
            implot.end_plot()

    def _plot_series(self, series: PlotSeries, index: int) -> None:
        """Plot one series (line / scatter / bar) from its typed coordinates.

        A ragged series is skipped *and logged*: the Hub's ``validate`` gate should
        have rejected it, so a fired warning means that gate has a gap, not that
        partial data is silently drawn as complete. An empty series is skipped
        silently — an honest "nothing to draw".
        """
        if series.is_ragged:
            logger.warning(
                "plot %r series[%d] %r is ragged (x=%d, y=%d) and was skipped; "
                "the Hub validate gate should have rejected it",
                self._elem.id,
                index,
                series.label,
                len(series.x),
                len(series.y),
            )
            return
        x_data = np.array(series.x, dtype=np.float64)
        y_data = np.array(series.y, dtype=np.float64)
        if len(x_data) == 0 or len(y_data) == 0:
            return
        imgui.push_id(index)
        try:
            self._draw(series.series_type, series.label, x_data, y_data)
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
            _BARS.plot(label, x_data, y_data)
