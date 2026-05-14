"""Tests for pure table filter logic — no ImGui dependency."""

from __future__ import annotations

import pytest

from punt_lux.display.table_renderer import (
    IndexedRow,
    _filter_indexed_rows,
    _get_filter_snapshot,
    _table_column_weights,
)
from punt_lux.protocol import TableFilter
from punt_lux.widget_state import WidgetState


@pytest.fixture()
def widget_state() -> WidgetState:
    return WidgetState()


@pytest.fixture()
def sample_rows() -> list[list[str]]:
    return [
        ["Alice", "Engineering", "Senior"],
        ["Bob", "Sales", "Junior"],
        ["Carol", "Engineering", "Junior"],
        ["Dave", "Marketing", "Senior"],
    ]


@pytest.fixture()
def indexed_rows(sample_rows: list[list[str]]) -> list[IndexedRow]:
    return list(enumerate(sample_rows))


def test_apply_table_filters_search(
    widget_state: WidgetState,
    sample_rows: list[list[str]],
    indexed_rows: list[IndexedRow],
) -> None:
    """Search filter keeps only rows matching the query in target columns."""
    filt = TableFilter(type="search", column_spec=[0, 1], label="Search")
    table_id = "t1"

    # Seed the widget state with a search query
    widget_state.set("__tbl_search_0_t1", "alice")

    result = _filter_indexed_rows([filt], indexed_rows, table_id, widget_state)

    assert len(result) == 1
    assert result[0][0] == 0  # original index preserved
    assert result[0][1][0] == "Alice"


def test_apply_table_filters_combo(
    widget_state: WidgetState,
    sample_rows: list[list[str]],
    indexed_rows: list[IndexedRow],
) -> None:
    """Combo filter keeps only rows whose column matches the selected item."""
    filt = TableFilter(
        type="combo",
        column_spec=1,
        items=["All", "Engineering", "Sales", "Marketing"],
        label="Dept",
    )
    table_id = "t2"

    # Select "Engineering" (index 1)
    widget_state.set("__tbl_combo_0_t2", 1)

    result = _filter_indexed_rows([filt], indexed_rows, table_id, widget_state)

    assert len(result) == 2
    names = [r[1][0] for r in result]
    assert names == ["Alice", "Carol"]


def test_filter_indexed_rows(
    widget_state: WidgetState,
    sample_rows: list[list[str]],
    indexed_rows: list[IndexedRow],
) -> None:
    """Original row indices are preserved through filtering."""
    filt = TableFilter(type="search", column_spec=2, label="Level")
    table_id = "t3"

    widget_state.set("__tbl_search_0_t3", "junior")

    result = _filter_indexed_rows([filt], indexed_rows, table_id, widget_state)

    # Bob (idx 1) and Carol (idx 2) are Junior
    orig_indices = [r[0] for r in result]
    assert orig_indices == [1, 2]


def test_column_weights() -> None:
    """Column widths calculated from header + cell string lengths, floored at 4.0."""
    columns = ["ID", "Name", "Description"]
    rows = [
        ["1", "Al", "A short desc"],
        ["2", "Bob", "Another description here"],
    ]

    weights = _table_column_weights(columns, rows, None)

    assert len(weights) == 3
    # "ID" header = 2 chars, cells "1"=1, "2"=1 => max 2 => floored to 4.0
    assert weights[0] == 4.0
    # "Name" header = 4 chars, cells "Al"=2, "Bob"=3 => max 4 => 4.0
    assert weights[1] == 4.0
    # "Description" header = 11, cells 12, 24 => max 24
    assert weights[2] == 24.0


def test_column_weights_explicit() -> None:
    """Explicit weights are returned directly when count matches."""
    columns = ["A", "B"]
    rows = [["x", "y"]]
    explicit = [10.0, 20.0]

    weights = _table_column_weights(columns, rows, explicit)

    assert weights == [10.0, 20.0]


def test_filter_snapshot_change_detection(widget_state: WidgetState) -> None:
    """Snapshot string changes when widget state for a filter changes."""
    filters = [
        TableFilter(type="search", column_spec=0, label="Search"),
        TableFilter(
            type="combo",
            column_spec=1,
            items=["All", "A", "B"],
            label="Cat",
        ),
    ]
    table_id = "t4"

    snap_before = _get_filter_snapshot(filters, table_id, widget_state)

    # Change the search value
    widget_state.set("__tbl_search_0_t4", "hello")

    snap_after = _get_filter_snapshot(filters, table_id, widget_state)

    assert snap_before != snap_after

    # Change the combo selection
    snap_mid = snap_after
    widget_state.set("__tbl_combo_1_t4", 2)

    snap_final = _get_filter_snapshot(filters, table_id, widget_state)

    assert snap_mid != snap_final
