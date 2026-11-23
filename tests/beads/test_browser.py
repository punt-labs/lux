"""The browser preserves load outcomes and puts successful rows in board order."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.beads.bd_command import BdOutput
from punt_lux.beads.beads_load import BeadsLoad
from punt_lux.beads.beads_result import BeadsFailure, BeadsRows
from punt_lux.beads.browser import BeadsBrowser


@pytest.mark.parametrize("all_issues", [False, True])
def test_loaded_rows_are_sorted_in_board_order(all_issues: bool) -> None:
    rows = BeadsRows.of(
        [
            {"id": "open", "status": "open", "priority": 0},
            {"id": "working", "status": "in_progress", "priority": 1},
        ]
    )
    load = BeadsLoad(rows, BdOutput.none(), 0.0)
    with patch("punt_lux.beads.browser.BeadsLoader.run", return_value=load) as run:
        result = BeadsBrowser().load(all_issues=all_issues).result
    run.assert_called_once_with(all_issues=all_issues)
    assert isinstance(result, BeadsRows)
    assert [row["id"] for row in result.issues] == ["working", "open"]


def test_empty_load_remains_a_success() -> None:
    load = BeadsLoad(BeadsRows.of([]), BdOutput.none(), 0.0)
    with patch("punt_lux.beads.browser.BeadsLoader.run", return_value=load):
        result = BeadsBrowser().load().result
    assert isinstance(result, BeadsRows)
    assert result.issues == []


def test_failed_load_keeps_its_reason() -> None:
    failure = BeadsFailure("database unavailable")
    load = BeadsLoad.failed(failure)
    with patch("punt_lux.beads.browser.BeadsLoader.run", return_value=load):
        result = BeadsBrowser().load().result
    assert result is failure
