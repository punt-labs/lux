"""Migration gate for the ABC ``plot`` leaf — Levels 1-5 + the crash defect.

A display-only leaf: a 2D chart whose ``series`` are a typed ``PlotSeries``
value family, no child elements and no interaction (Level 4 is N/A). The bead's
named defect is foregrounded here: a malformed series (non-string label,
non-numeric coordinate, or ragged ``x``/``y``) used to raise through the render
loop and take the display down. It is now rejected at the Hub — type faults at
the wire boundary (``PlotSeries.decode_all``), the ragged-length invariant in
``PlotElement.validate`` — so a malformed plot never reaches the display, proven
by a ``show()`` rejection of the exact payload class. The renderer keeps its
label ``TypeError`` guard as defense-in-depth.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from punt_lux.display import geometry_capture
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.plot import ImGuiPlotRenderer, _BarSeriesPlotter
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import GroupElement, PlotElement
from punt_lux.protocol.elements.plot_series import PlotSeries
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

from .geometry_doubles import EXPECTED_RECT, FakeGeomImgui, GeomFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


# -- helpers ----------------------------------------------------------------


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    return sock


def _inspect(server: DisplayServer, *elements: Element) -> QueryResponse:
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


def _plot() -> PlotElement:
    return PlotElement(
        id="pl1",
        title="Trend",
        x_label="t",
        y_label="v",
        series=(
            PlotSeries("y", "line", (1.0, 2.0, 3.0), (10.0, 20.0, 15.0)),
            PlotSeries("pts", "scatter", (1.0, 2.0), (5.0, 8.0)),
        ),
    )


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_plot_roundtrips_to_abc(self) -> None:
        restored = _decode(_plot().to_dict())
        assert isinstance(restored, PlotElement)
        assert restored.title == "Trend"
        assert restored.series[0] == PlotSeries(
            "y", "line", (1.0, 2.0, 3.0), (10.0, 20.0, 15.0)
        )
        assert restored.series[1].series_type == "scatter"

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        wire = PlotElement(id="pl1", tooltip="hover").to_dict()
        assert wire["tooltip"] == "hover"
        restored = _decode(wire)
        assert isinstance(restored, PlotElement)
        assert restored.tooltip == "hover"

    def test_wire_shape_carries_typed_series(self) -> None:
        wire = PlotElement(
            id="pl1", series=(PlotSeries("y", "bar", (1.0,), (2.0,)),)
        ).to_dict()
        assert wire["series"] == [{"label": "y", "type": "bar", "x": [1.0], "y": [2.0]}]


# -- the named crash defect: reject malformed series at the Hub -------------


class TestCrashDefectRejectedAtHub:
    def test_non_str_label_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"series\[0\].label must be a string"):
            PlotElement.from_dict(
                {
                    "kind": "plot",
                    "id": "pl1",
                    "series": [{"label": 123, "x": [1], "y": [2]}],
                }
            )

    def test_non_numeric_coordinate_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"series\[0\].x\[1\] must be a number"):
            PlotElement.from_dict(
                {
                    "kind": "plot",
                    "id": "pl1",
                    "series": [{"label": "y", "x": [1, "bad"], "y": [2, 3]}],
                }
            )

    def test_unknown_series_type_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"series\[0\].type must be one of"):
            PlotElement.from_dict(
                {"kind": "plot", "id": "pl1", "series": [{"label": "y", "type": "pie"}]}
            )

    def test_ragged_series_reported_by_validate(self) -> None:
        plot = PlotElement(
            id="pl1", series=(PlotSeries("y", "line", (1.0, 2.0), (3.0,)),)
        )
        errors = plot.validate()
        assert len(errors) == 1
        assert errors[0].element_kind == "plot"
        assert "x has 2 points, y has 1" in errors[0].message

    def test_every_ragged_series_collects_at_once(self) -> None:
        plot = PlotElement(
            id="pl1",
            series=(
                PlotSeries("a", "line", (1.0,), ()),
                PlotSeries("ok", "line", (1.0,), (2.0,)),
                PlotSeries("b", "bar", (1.0, 2.0), (3.0,)),
            ),
        )
        assert len(plot.validate()) == 2

    def test_valid_plot_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([_plot()]).ok

    @patch(_CLIENT_GET)
    def test_show_rejects_the_crash_payload_that_killed_the_display(
        self, mock_get: MagicMock
    ) -> None:
        """The exact non-str-label payload that used to fault mid-render is refused."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "plot",
                    "id": "pl1",
                    "series": [{"label": 42, "x": [1], "y": [2]}],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "label must be a string" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_ragged_series(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "plot",
                    "id": "pl1",
                    "series": [{"label": "y", "x": [1, 2], "y": [3]}],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[plot 'pl1']" in result
        client.show.assert_not_called()


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_plot_crosses_as_pickled_entry(self) -> None:
        wire = message_to_dict(SceneMessage(id="s1", elements=[_plot()], frame_id="s1"))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC plot must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, PlotElement)
        assert r.series[0].label == "y"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_plot_renderer_factory(self) -> None:
        received = message_from_dict(
            message_to_dict(SceneMessage(id="s1", elements=[_plot()], frame_id="s1"))
        )
        assert isinstance(received, SceneMessage)
        plot = received.elements[0]
        assert isinstance(plot, PlotElement)
        before = plot._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert plot._renderer_factory is factory


# -- ABC decode nesting -----------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_plot_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "plot", "id": "pl1"}],
        }
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], PlotElement)


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_plot_is_recorded(self) -> None:
        resp = _inspect(_server(), _plot())
        assert _record(resp, "pl1")["kind"] == "plot"

    def test_plot_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), PlotElement(id="pl1", title="T"))
        props = _record(resp, "pl1")["props"]
        assert props == {
            "title": "T",
            "x_label": "",
            "y_label": "",
            "width": -1.0,
            "height": 300.0,
            "series": [],
            "tooltip": None,
        }


class TestPatchPath:
    def test_apply_patch_replaces_series_in_place(self) -> None:
        plot = PlotElement(
            id="pl1", series=(PlotSeries("old", "line", (1.0,), (2.0,)),)
        )
        returned = plot.apply_patch(
            {"series": [{"label": "new", "type": "bar", "x": [1], "y": [2]}]}
        )
        assert returned is plot
        assert plot.series == (PlotSeries("new", "bar", (1.0,), (2.0,)),)

    def test_apply_patch_rejects_malformed_series(self) -> None:
        plot = PlotElement(
            id="pl1", series=(PlotSeries("keep", "line", (1.0,), (2.0,)),)
        )
        with pytest.raises(ValueError, match="label must be a string"):
            plot.apply_patch({"series": [{"label": 7, "x": [1], "y": [2]}]})
        assert plot.series == (PlotSeries("keep", "line", (1.0,), (2.0,)),)

    def test_apply_patch_sets_title_and_axes(self) -> None:
        plot = PlotElement(id="pl1")
        plot.apply_patch({"title": "T", "x_label": "x", "y_label": "y"})
        assert (plot.title, plot.x_label, plot.y_label) == ("T", "x", "y")


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_plot_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(
            PlotElement(id="pl1", series=(PlotSeries("y", "line", (1.0,), (2.0,)),))
        )
        assert encoded["kind"] == "plot"
        assert encoded["series"] == [
            {"label": "y", "type": "line", "x": [1.0], "y": [2.0]}
        ]


# -- painted geometry: the leaf records a rect through the measuring group ---


def test_plot_adapter_records_a_painted_rect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geometry_capture, "imgui", FakeGeomImgui())
    monkeypatch.setattr("punt_lux.display.renderers.imgui.plot.imgui", MagicMock())
    monkeypatch.setattr("punt_lux.display.renderers.imgui.plot.implot", MagicMock())
    factory = GeomFactory()
    factory.geometry.enter_scene("s1")

    adapter = ImGuiPlotRenderer(_plot(), cast("ImGuiRendererFactory", factory))
    adapter.paint()
    factory.geometry.complete()

    geom = factory.geometry.recorder.snapshot().element_for("s1", "pl1")
    assert geom is not None
    assert geom.rect == EXPECTED_RECT


# -- silent-failure guards: no quiet data loss on the render path -----------

_PLOT_MOD = "punt_lux.display.renderers.imgui.plot"


# The two plot_bars overloads imgui-bundle declares, as their doc-line signatures.
_EXPLICIT_X_DOC = (
    "plot_bars(label_id: str, xs: ndarray[writable=False], "
    "ys: ndarray[writable=False], bar_size: float, spec: Spec | None = None) -> None"
)
_Y_ONLY_DOC = (
    "plot_bars(label_id: str, values: ndarray[writable=False], "
    "bar_size: float = 0.67, shift: float = 0, spec: Spec | None = None) -> None"
)


def _implot_with_signature(doc: str) -> MagicMock:
    """A fake implot whose plot_bars declares the given signature and counts calls."""
    implot = MagicMock()
    implot.plot_bars.__doc__ = doc
    return implot


class TestBarSignatureProbe:
    def test_explicit_x_binding_keeps_x_and_stays_silent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        implot = _implot_with_signature(_EXPLICIT_X_DOC)
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", implot)
        plotter = _BarSeriesPlotter()
        with caplog.at_level(logging.WARNING):
            plotter.plot("bars", np.array([10.0, 20.0]), np.array([1.0, 2.0]))
        assert not caplog.records
        assert len(implot.plot_bars.call_args_list[-1].args) == 4  # label, xs, ys, size

    def test_genuine_typeerror_propagates_on_the_first_series(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        implot = _implot_with_signature(_EXPLICIT_X_DOC)
        implot.plot_bars.side_effect = TypeError("genuine array error")
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", implot)
        plotter = _BarSeriesPlotter()
        with pytest.raises(TypeError, match="genuine array error"):
            plotter.plot("bad", np.array([1.0]), np.array([2.0]))

    def test_y_only_binding_warns_once_on_non_index_x(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        implot = _implot_with_signature(_Y_ONLY_DOC)
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", implot)
        plotter = _BarSeriesPlotter()
        x = np.array([10.0, 20.0, 30.0])
        y = np.array([1.0, 2.0, 3.0])
        with caplog.at_level(logging.WARNING):
            plotter.plot("first", x, y)
            plotter.plot("second", x, y)
        warnings = [r for r in caplog.records if "takes no x argument" in r.message]
        assert len(warnings) == 1  # warned once
        assert len(implot.plot_bars.call_args_list[-1].args) == 3  # label, values, size

    def test_y_only_binding_is_silent_on_index_ramp(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        implot = _implot_with_signature(_Y_ONLY_DOC)
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", implot)
        plotter = _BarSeriesPlotter()
        with caplog.at_level(logging.WARNING):
            plotter.plot("ramp", np.array([0.0, 1.0, 2.0]), np.array([5.0, 6.0, 7.0]))
        assert not caplog.records  # y-only faithfully renders an index ramp

    def test_unparseable_signature_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        implot = _implot_with_signature("no signature here")
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", implot)
        with pytest.raises(RuntimeError, match="cannot read implot"):
            _BarSeriesPlotter()


class TestRaggedSeriesIsLogged:
    def test_ragged_series_warns_with_id_index_and_lengths(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(f"{_PLOT_MOD}.imgui", MagicMock())
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", MagicMock())
        plot = PlotElement(
            id="pl1", series=(PlotSeries("y", "line", (1.0, 2.0), (3.0,)),)
        )
        renderer = ImGuiPlotRenderer(plot, cast("ImGuiRendererFactory", MagicMock()))
        with caplog.at_level(logging.WARNING):
            renderer._plot_series(plot.series[0], 0)
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "ragged" in message
        assert "'pl1'" in message
        assert "x=2" in message
        assert "y=1" in message

    def test_empty_series_is_skipped_silently(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(f"{_PLOT_MOD}.imgui", MagicMock())
        monkeypatch.setattr(f"{_PLOT_MOD}.implot", MagicMock())
        plot = PlotElement(id="pl1", series=(PlotSeries("y", "line", (), ()),))
        renderer = ImGuiPlotRenderer(plot, cast("ImGuiRendererFactory", MagicMock()))
        with caplog.at_level(logging.WARNING):
            renderer._plot_series(plot.series[0], 0)
        assert not caplog.records  # honest empty — nothing to draw, nothing to warn
