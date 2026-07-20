# pyright: reportMissingModuleSource=false
"""PlotRenderer dispatches each series type and scopes ids on the ImGui stack.

The renderer under test is real; the mock-based tests fake ImGui and ImPlot at
the render boundary and assert the dispatch plus the ``push_id`` scoping the
renderer relies on. The integration tests drive a real headless ImGui/ImPlot
frame to prove that ``push_id`` actually gives same-label series distinct
ImPlot ids — the behavior a mock cannot model — including a label ending in
"#", which now renders verbatim instead of being truncated by an appended
delimiter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from punt_lux.display.renderers.leaf_widget_renderer import LeafWidgetRenderer
from punt_lux.display.renderers.plot_renderer import PlotRenderer
from punt_lux.protocol.elements.plot_element import PlotElement


def _vec2(w: float, h: float) -> tuple[float, float]:
    """Stand in for ``ImVec2`` — the renderer only forwards the pair."""
    return (w, h)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    implot: MagicMock,
    imgui: MagicMock,
) -> None:
    module = "punt_lux.display.renderers.plot_renderer"
    monkeypatch.setattr(f"{module}.implot", implot)
    monkeypatch.setattr(f"{module}.imgui", imgui)
    monkeypatch.setattr(f"{module}.ImVec2", _vec2)


def test_plot_renderer_satisfies_leaf_widget_protocol() -> None:
    assert isinstance(PlotRenderer(), LeafWidgetRenderer)


def test_render_dispatches_each_series_type(monkeypatch: pytest.MonkeyPatch) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = True
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
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


def test_render_passes_labels_and_title_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No "##" surgery: the title and labels reach ImPlot exactly as given."""
    implot = MagicMock()
    implot.begin_plot.return_value = True
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
    plot = PlotElement(
        id="p",
        title="Voltage",
        series=[{"type": "line", "x": [1], "y": [2], "label": "C#"}],
    )

    PlotRenderer().render(plot)

    assert implot.begin_plot.call_args.args[0] == "Voltage"
    assert implot.plot_line.call_args.args[0] == "C#"


def test_render_scopes_plot_and_each_series_on_the_id_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plot pushes its element id; each series pushes its index; all pop."""
    implot = MagicMock()
    implot.begin_plot.return_value = True
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
    plot = PlotElement(
        id="pid",
        series=[
            {"type": "line", "x": [1, 2], "y": [3, 4]},
            {"type": "line", "x": [1, 2], "y": [5, 6]},
        ],
    )

    PlotRenderer().render(plot)

    pushed = [call.args[0] for call in imgui.push_id.call_args_list]
    assert pushed == ["pid", 0, 1]
    assert imgui.pop_id.call_count == 3
    labels = [call.args[0] for call in implot.plot_line.call_args_list]
    assert labels == ["data", "data"]


def test_render_pops_plot_id_even_when_plot_not_begun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = False
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
    plot = PlotElement(
        id="p",
        series=[{"type": "line", "x": [1], "y": [2], "label": "L"}],
    )

    PlotRenderer().render(plot)

    imgui.push_id.assert_called_once_with("p")
    imgui.pop_id.assert_called_once_with()
    implot.plot_line.assert_not_called()
    implot.end_plot.assert_not_called()


def test_series_labels_default_and_reject() -> None:
    """Missing labels default to "data"; a non-str label raises TypeError."""
    assert PlotRenderer._series_labels([{"type": "line"}, {"label": "S"}]) == [
        "data",
        "S",
    ]
    with pytest.raises(TypeError):
        PlotRenderer._series_labels([{"label": 5}])


def test_render_rejects_non_str_label_before_opening_implot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed label is rejected before any ImGui/ImPlot state is opened."""
    implot = MagicMock()
    implot.begin_plot.return_value = True
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
    plot = PlotElement(
        id="p",
        series=[{"type": "line", "x": [1], "y": [2], "label": None}],
    )

    with pytest.raises(TypeError):
        PlotRenderer().render(plot)

    implot.begin_plot.assert_not_called()
    imgui.push_id.assert_not_called()


def test_render_ends_plot_when_the_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-body failure still balances the plot and id stacks.

    A valid label passes the up-front check and opens the plot; a raising
    plot call must still reach end_plot and pop every pushed id.
    """
    implot = MagicMock()
    implot.begin_plot.return_value = True
    implot.plot_line.side_effect = RuntimeError("boom")
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
    plot = PlotElement(
        id="p",
        series=[{"type": "line", "x": [1], "y": [2], "label": "L"}],
    )

    with pytest.raises(RuntimeError):
        PlotRenderer().render(plot)

    implot.end_plot.assert_called_once_with()
    assert imgui.pop_id.call_count == 2


def test_render_skips_series_with_empty_data(monkeypatch: pytest.MonkeyPatch) -> None:
    implot = MagicMock()
    implot.begin_plot.return_value = True
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
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
    imgui = MagicMock()
    _patch(monkeypatch, implot, imgui)
    plot = PlotElement(
        id="p",
        series=[{"type": "bar", "x": [1], "y": [2], "label": "B"}],
    )

    PlotRenderer().render(plot)

    assert implot.plot_bars.call_count == 2


# --- Real headless ImGui/ImPlot: prove push_id disambiguates item ids. ---

_XS = np.array([1.0, 2.0], dtype=np.float64)
_YS = np.array([3.0, 4.0], dtype=np.float64)


def _plot_series_item_count(entries: list[tuple[str, int]]) -> int:
    """Return the ImPlot item count after plotting each (label, index) entry.

    Each entry is scoped by ``imgui.push_id(index)`` exactly as the renderer
    scopes a series, so the count reflects how many distinct ImPlot items the
    id stack produced.
    """
    from imgui_bundle import ImVec2, imgui, implot
    from imgui_bundle.implot import internal as implot_internal

    imgui.create_context()
    implot.create_context()
    try:
        io = imgui.get_io()
        io.display_size = ImVec2(1024, 768)
        io.delta_time = 1.0 / 60.0
        io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
        imgui.new_frame()
        imgui.begin("w")
        count = 0
        if implot.begin_plot("Chart", ImVec2(400, 300)):
            for label, index in entries:
                imgui.push_id(index)
                implot.plot_line(label, _XS, _YS)
                imgui.pop_id()
            count = implot_internal.get_current_plot().items.get_item_count()
            implot.end_plot()
        imgui.end()
        imgui.render()
        return count
    finally:
        implot.destroy_context()
        imgui.destroy_context()


@pytest.mark.integration
def test_push_id_gives_labelless_series_distinct_items() -> None:
    """Two label-less "data" series scoped by index become two ImPlot items."""
    assert _plot_series_item_count([("data", 0), ("data", 1)]) == 2


@pytest.mark.integration
def test_push_id_keeps_trailing_hash_labels_distinct() -> None:
    """A label ending in "#" stays verbatim and still disambiguates by index.

    Passed raw with no appended "##", "C#" renders unmodified and, scoped by
    index, registers two distinct items — the collision an appended delimiter
    would have reintroduced by forming a "###" id-reset run.
    """
    assert _plot_series_item_count([("C#", 0), ("C#", 1)]) == 2
