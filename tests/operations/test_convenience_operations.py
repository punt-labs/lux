"""ConvenienceOperations compose an element tree and delegate to render."""

from __future__ import annotations

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.operations import (
    OpError,
    RenderDashboardRequest,
    RenderTableRequest,
    SceneShown,
)
from punt_lux.operations.conveniences import ConvenienceOperations
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope

_LOCAL = Scope(ConnectionId("local"))


class _Recorder:
    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_cleared(self) -> None:  # pragma: no cover - unused here
        pass

    def mark_menus(self, bar: object, items: object) -> None:  # pragma: no cover
        pass


def _conveniences(store: HubDisplay) -> ConvenienceOperations:
    scenes = SceneOperations(store, _Recorder(), hub_element_factory)
    return ConvenienceOperations(scenes)


def test_render_table_installs_a_table_element() -> None:
    store = HubDisplay()
    request = RenderTableRequest.parse(
        {"scene_id": "tbl", "columns": ["A"], "rows": [["x"]]}
    )
    result = _conveniences(store).render_table(request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    table = store.resolve(SceneId("tbl"), ElementId("table"))
    assert table.kind == "table"


def test_render_dashboard_installs_metric_and_table_sections() -> None:
    store = HubDisplay()
    request = RenderDashboardRequest.parse(
        {
            "scene_id": "dash",
            "metrics": [{"label": "Total", "value": "42"}],
            "table_columns": ["Name"],
            "table_rows": [["a"]],
        }
    )
    result = _conveniences(store).render_dashboard(request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    assert store.resolve(SceneId("dash"), ElementId("metrics-row")).kind == "group"
    assert store.resolve(SceneId("dash"), ElementId("dashboard-table")).kind == "table"


def test_render_table_passes_an_op_error_straight_through() -> None:
    error = OpError(code="invalid_request", reason="bad")
    assert _conveniences(HubDisplay()).render_table(error, scope=_LOCAL) is error


def test_render_dashboard_passes_an_op_error_straight_through() -> None:
    error = OpError(code="invalid_request", reason="bad")
    assert _conveniences(HubDisplay()).render_dashboard(error, scope=_LOCAL) is error
