"""PlotRenderer dispatches each series type to its ImPlot call.

The renderer under test is real; only the ImPlot backend is faked (a mock
at the render boundary). Each series type routes to the matching plot call,
and the bar fallback re-issues without the width arg on a ``TypeError`` —
behaviour identical to the pre-extraction inline body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.renderers.leaf_widget_renderer import LeafWidgetRenderer
from punt_lux.display.renderers.plot_renderer import PlotRenderer
from punt_lux.protocol.elements.plot_element import PlotElement

if TYPE_CHECKING:
    import pytest


def _vec2(w: float, h: float) -> tuple[float, float]:
    """Stand in for ``ImVec2`` — the renderer only forwards the pair."""
    return (w, h)


def _patch(monkeypatch: pytest.MonkeyPatch, implot: MagicMock) -> None:
    monkeypatch.setattr("punt_lux.display.renderers.plot_renderer.implot", implot)
    monkeypatch.setattr("punt_lux.display.renderers.plot_renderer.ImVec2", _vec2)


def test_plot_renderer_satisfies_leaf_widget_protocol() -> None:
    assert isinstance(PlotRenderer(), LeafWidgetRenderer)


def test_render_dispatches_each_series_type(monkeypatch: pytest.MonkeyPatch) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = True
    _patch(monkeypatch, implot)
    plot = PlotElement(
        id="p",
        title="Chart",
        x_label="x",
        y_label="y",
        series=[
            {"type": "line", "x": [1, 2], "y": [3, 4], "label": "L"},
            {"type": "scatter", "x": [1], "y": [2], "label": "S"},
            {"type": "bar", "x": [1], "y": [2], "label": "B"},
        ],
    )

    PlotRenderer().render(plot)

    implot.setup_axes.assert_called_once_with("x", "y")
    assert implot.plot_line.call_count == 1
    assert implot.plot_scatter.call_count == 1
    assert implot.plot_bars.call_count == 1
    implot.end_plot.assert_called_once()


def test_render_skips_series_with_empty_data(monkeypatch: pytest.MonkeyPatch) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = True
    _patch(monkeypatch, implot)
    plot = PlotElement(
        id="p",
        series=[{"type": "line", "x": [], "y": [], "label": "empty"}],
    )

    PlotRenderer().render(plot)

    implot.plot_line.assert_not_called()


def test_bar_falls_back_without_width_on_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = True
    implot.plot_bars.side_effect = [TypeError, None]
    _patch(monkeypatch, implot)
    plot = PlotElement(
        id="p",
        series=[{"type": "bar", "x": [1], "y": [2], "label": "B"}],
    )

    PlotRenderer().render(plot)

    assert implot.plot_bars.call_count == 2


def test_render_paints_nothing_when_plot_not_begun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = False
    _patch(monkeypatch, implot)
    plot = PlotElement(
        id="p",
        series=[{"type": "line", "x": [1], "y": [2], "label": "L"}],
    )

    PlotRenderer().render(plot)

    implot.plot_line.assert_not_called()
    implot.end_plot.assert_not_called()
