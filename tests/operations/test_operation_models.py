"""The request/result models: never-raising parse and the error contract."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from punt_lux.operations import (
    DisplayModeRequest,
    OpError,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    UpdateRequest,
)
from punt_lux.operations.models.patches import RemovePatch, SetPatch
from punt_lux.operations.models.render import FrameSpec

if TYPE_CHECKING:
    from collections.abc import Mapping


def test_parse_reports_a_bad_layout_as_its_legacy_message() -> None:
    result = RenderRequest.parse({"scene_id": "s", "elements": [], "layout": "x"})
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert result.reason == "layout must be single/rows/columns/grid, got 'x'"


def test_parse_reports_a_bad_frame_layout_as_its_legacy_message() -> None:
    result = RenderRequest.parse(
        {"scene_id": "s", "elements": [], "frame": {"layout": "grid"}}
    )
    assert isinstance(result, OpError)
    assert result.reason == "frame_layout must be 'tab' or 'stack', got 'grid'"


def test_parse_reports_a_bad_frame_size_as_its_legacy_message() -> None:
    result = RenderRequest.parse(
        {"scene_id": "s", "elements": [], "frame": {"size": [800]}}
    )
    assert isinstance(result, OpError)
    assert result.reason == "frame_size must be [width, height]"


def test_parse_accepts_a_valid_request() -> None:
    result = RenderRequest.parse({"scene_id": "s", "elements": []})
    assert isinstance(result, RenderRequest)


def test_presentation_defaults_the_frame_from_the_scene_id() -> None:
    request = RenderRequest(scene_id="scene", elements=[], frame=FrameSpec())
    presentation = request.presentation()
    assert presentation.frame_id == "scene"
    assert presentation.frame_title == "scene"


def test_update_parse_maps_wire_shapes_to_variants() -> None:
    result = UpdateRequest.parse(
        [{"id": "a", "set": {"x": 1}}, {"id": "b", "remove": True}]
    )
    assert isinstance(result, UpdateRequest)
    assert result.patches == [SetPatch(id="a", set={"x": 1}), RemovePatch(id="b")]
    assert result.to_wire() == [
        {"id": "a", "set": {"x": 1}},
        {"id": "b", "remove": True},
    ]


def test_update_parse_reports_a_malformed_patch_as_the_writer_would() -> None:
    result = UpdateRequest.parse([{"id": "hdr"}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "hdr" in result.reason


def test_display_mode_parse_maps_y_and_n() -> None:
    on = DisplayModeRequest.parse("y", str(Path.cwd()))
    off = DisplayModeRequest.parse("n", str(Path.cwd()))
    assert isinstance(on, DisplayModeRequest)
    assert isinstance(off, DisplayModeRequest)
    assert (on.mode, off.mode) == ("on", "off")


def test_display_mode_parse_rejects_an_unknown_mode_without_raising() -> None:
    result = DisplayModeRequest.parse("maybe", str(Path.cwd()))
    assert isinstance(result, OpError)
    assert result.reason == "Invalid mode 'maybe'. Use 'y' or 'n'."


def test_display_mode_parse_rejects_a_relative_repo_without_raising() -> None:
    result = DisplayModeRequest.parse("y", "relative/path")
    assert isinstance(result, OpError)
    assert "absolute path" in result.reason


def test_op_error_is_a_discriminated_error() -> None:
    error = OpError(code="timeout", reason="slow")
    assert error.kind == "error"
    assert error.code == "timeout"


# --- The never-raising matrix: parse yields an OpError, never an exception. ---


def test_render_parse_falls_back_on_wrong_typed_frame_flags() -> None:
    result = RenderRequest.parse(
        {"scene_id": "s", "elements": [], "frame": {"flags": "not-a-mapping"}}
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert result.reason


def test_render_parse_falls_back_on_wrong_typed_scene_id() -> None:
    result = RenderRequest.parse({"scene_id": 123, "elements": []})
    assert isinstance(result, OpError)
    assert result.reason


def test_render_parse_falls_back_on_wrong_typed_elements() -> None:
    result = RenderRequest.parse({"scene_id": "s", "elements": "nope"})
    assert isinstance(result, OpError)
    assert result.reason


def test_render_parse_falls_back_on_empty_mapping() -> None:
    result = RenderRequest.parse({})
    assert isinstance(result, OpError)
    assert result.reason


def test_render_parse_falls_back_on_non_mapping_input() -> None:
    result = RenderRequest.parse(cast("Mapping[str, object]", "not-a-mapping"))
    assert isinstance(result, OpError)
    assert result.reason


def test_update_parse_falls_back_on_missing_id() -> None:
    result = UpdateRequest.parse([{"set": {"a": 1}}])
    assert isinstance(result, OpError)
    assert "id" in result.reason


def test_update_parse_falls_back_on_non_boolean_remove() -> None:
    result = UpdateRequest.parse([{"id": "x", "remove": "yes"}])
    assert isinstance(result, OpError)
    assert "x" in result.reason


def test_render_table_parse_falls_back_on_missing_columns() -> None:
    result = RenderTableRequest.parse({"scene_id": "s", "rows": []})
    assert isinstance(result, OpError)
    assert result.reason


def test_render_dashboard_parse_falls_back_and_names_the_missing_field() -> None:
    result = RenderDashboardRequest.parse(
        {"scene_id": "s", "metrics": [{"label": "x"}]}
    )
    assert isinstance(result, OpError)
    # The fallback carries the location path so the missing field is named.
    assert result.reason == "metrics.0.value: Field required"


def test_render_dashboard_parse_rejects_rows_without_columns() -> None:
    result = RenderDashboardRequest.parse({"scene_id": "s", "table_rows": [["a"]]})
    assert isinstance(result, OpError)
    assert result.reason == "table_rows requires table_columns"
