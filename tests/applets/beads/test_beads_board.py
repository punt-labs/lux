"""A board builds data requests for populated, empty, and failed loads."""

from __future__ import annotations

from punt_lux.applets.beads.beads_board import BeadsBoard
from punt_lux.applets.beads.beads_result import BeadsFailure, BeadsRows
from punt_lux.wire.operations import RenderRequest, RenderTableRequest
from tests.applets.board_doubles import ISSUE


def test_populated_board_builds_a_table_in_its_project_frame() -> None:
    board = BeadsBoard.for_project("lux")
    request = board.request(BeadsRows.of([ISSUE]))
    assert isinstance(request, RenderTableRequest)
    assert request.scene_id == board.frame_id == "beads-lux"
    assert request.frame_id == board.frame_id
    assert request.rows[0][0] == ISSUE["id"]
    assert request.title == "Beads: lux"


def test_empty_board_builds_an_empty_message_in_the_same_frame() -> None:
    board = BeadsBoard.for_project("lux")
    request = board.request(BeadsRows.of([]))
    assert isinstance(request, RenderRequest)
    assert request.scene_id == board.frame_id
    assert request.frame is not None
    assert request.frame.frame_id == board.frame_id
    assert request.elements[0]["content"] == "No active issues."


def test_failed_board_builds_a_visible_error_in_the_same_frame() -> None:
    board = BeadsBoard.for_project("lux")
    request = board.request(BeadsFailure("database unavailable"))
    assert isinstance(request, RenderRequest)
    assert request.scene_id == board.frame_id
    assert request.elements[0]["content"] == "bd unavailable — database unavailable"
    assert request.elements[0]["color"] == "#FF5555"
