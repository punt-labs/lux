"""TableWire — the extracted rows/columns wire-shape coercion.

Structural checks only (a ragged row or a non-scalar cell is validate's job); the
codec and the element's patch setters share these, so they are pinned directly.
"""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.table_wire import TableWire


def test_rows_from_wire_coerces_lists_to_tuples() -> None:
    assert TableWire.rows_from_wire([["a", 1], ["b", 2]]) == (("a", 1), ("b", 2))


def test_rows_from_wire_rejects_a_non_list() -> None:
    with pytest.raises(ValueError, match="rows must be a list of rows, got str"):
        TableWire.rows_from_wire("nope")


def test_rows_from_wire_rejects_a_non_list_row_naming_the_index() -> None:
    with pytest.raises(ValueError, match="row 1 must be a list of cells"):
        TableWire.rows_from_wire([["ok"], "bad"])


def test_columns_from_wire_returns_a_string_tuple() -> None:
    assert TableWire.columns_from_wire(["ID", "Name"]) == ("ID", "Name")


def test_str_list_rejects_a_non_string_entry_naming_the_field() -> None:
    with pytest.raises(ValueError, match="flags must be a list of strings, got list"):
        TableWire.str_list([1, 2], "flags")
