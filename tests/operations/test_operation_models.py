"""The request/result models: never-raising parse and the error contract."""

from __future__ import annotations

import pytest

from punt_lux.operations import (
    DisplayModeRequest,
    OpError,
    RenderRequest,
    UpdateRequest,
)
from punt_lux.operations.models.render import FrameSpec


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


def test_update_parse_wraps_the_patch_list() -> None:
    result = UpdateRequest.parse([{"id": "x", "set": {"a": 1}}])
    assert isinstance(result, UpdateRequest)
    assert result.patches == [{"id": "x", "set": {"a": 1}}]


def test_from_toggle_maps_y_and_n() -> None:
    assert DisplayModeRequest.from_toggle("y", "/repo").mode == "on"
    assert DisplayModeRequest.from_toggle("n", "/repo").mode == "off"


def test_from_toggle_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Invalid mode"):
        DisplayModeRequest.from_toggle("maybe", "/repo")


def test_op_error_is_a_discriminated_error() -> None:
    error = OpError(code="timeout", reason="slow")
    assert error.kind == "error"
    assert error.code == "timeout"
