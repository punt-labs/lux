"""Component-appropriate self-validation on the table element.

The table decides what "valid" means for *itself*: rows must fit the
declared columns and cells must be renderable scalars. These tests cover
the table's ``validate()`` in isolation; the tree-walk and ``show``
integration are covered in ``tests/domain/test_validation_walk.py`` and
``tests/test_tools.py``.
"""

from __future__ import annotations

from punt_lux.protocol.elements.layout import GroupElement
from punt_lux.protocol.elements.table import TableElement


class TestTableValidate:
    def test_well_formed_table_has_no_errors(self) -> None:
        table = TableElement(
            id="sales",
            columns=["Name", "Score"],
            rows=[["Alice", 95], ["Bob", 87]],
        )
        assert table.validate() == ()

    def test_scalar_cell_kinds_are_all_renderable(self) -> None:
        table = TableElement(
            id="mixed",
            columns=["s", "i", "f", "b", "n"],
            rows=[["x", 1, 2.5, True, None]],
        )
        assert table.validate() == ()

    def test_short_row_reports_a_mismatch(self) -> None:
        table = TableElement(
            id="sales",
            columns=["Name", "Score", "Rank"],
            rows=[["Alice", 95]],
        )
        errors = table.validate()
        assert len(errors) == 1
        assert errors[0].element_id == "sales"
        assert errors[0].element_kind == "table"
        assert "2 cell(s)" in errors[0].message
        assert "3 column(s)" in errors[0].message

    def test_long_row_reports_a_mismatch(self) -> None:
        table = TableElement(
            id="sales",
            columns=["Name"],
            rows=[["Alice", "extra"]],
        )
        errors = table.validate()
        assert len(errors) == 1
        assert "2 cell(s)" in errors[0].message

    def test_unrenderable_cell_reports_its_type(self) -> None:
        table = TableElement(
            id="nested",
            columns=["Name", "Tags"],
            rows=[["Alice", ["a", "b"]]],
        )
        errors = table.validate()
        assert len(errors) == 1
        assert "column 1" in errors[0].message
        assert "list" in errors[0].message

    def test_every_bad_row_and_cell_collects_at_once(self) -> None:
        # One short row AND one dict cell: two independent errors, no fail-fast.
        table = TableElement(
            id="messy",
            columns=["A", "B"],
            rows=[
                ["only-one"],  # short row
                ["ok", {"k": "v"}],  # unrenderable cell
            ],
        )
        errors = table.validate()
        assert len(errors) == 2
        messages = " ".join(e.message for e in errors)
        assert "1 cell(s)" in messages
        assert "dict" in messages

    def test_empty_table_is_valid(self) -> None:
        assert TableElement(id="empty").validate() == ()

    def test_non_list_row_reports_error_not_crash(self) -> None:
        # A scalar row would make ``len(row)`` raise TypeError; the guard
        # turns it into an actionable error instead of a crash.
        table = TableElement(id="scalars", columns=["A"], rows=[1, 2])  # type: ignore[list-item]  # deliberately malformed
        errors = table.validate()
        assert len(errors) == 2
        assert all("is not a list of cells" in e.message for e in errors)
        assert errors[0].element_kind == "table"

    def test_zero_columns_with_nonempty_row_is_a_mismatch(self) -> None:
        table = TableElement(id="empty_cols", columns=[], rows=[["x"]])
        errors = table.validate()
        assert len(errors) == 1
        assert "1 cell(s)" in errors[0].message
        assert "0 column(s)" in errors[0].message

    def test_row_wrong_length_and_bad_cell_reports_two_errors(self) -> None:
        # A single row that is BOTH too long AND holds an unrenderable cell
        # yields two independent errors — no fail-fast.
        table = TableElement(id="both", columns=["A"], rows=[["x", {"k": "v"}]])
        errors = table.validate()
        assert len(errors) == 2
        messages = " ".join(e.message for e in errors)
        assert "2 cell(s)" in messages
        assert "1 column(s)" in messages
        assert "dict" in messages

    def test_null_rows_reports_error_not_crash(self) -> None:
        # ``{"rows": null}`` decodes to ``None`` (dict.get returns the present
        # value, not the default); ``len``/iteration would crash without the
        # guard. It must be reported like any other malformation.
        table = TableElement(id="nr", columns=["A"], rows=None)  # type: ignore[arg-type]  # wire present-null
        errors = table.validate()
        assert len(errors) == 1
        assert "rows must be a list of rows" in errors[0].message
        assert errors[0].element_kind == "table"

    def test_null_columns_reports_error_not_crash(self) -> None:
        table = TableElement(id="nc", columns=None, rows=[["x"]])  # type: ignore[arg-type]  # wire present-null
        errors = table.validate()
        assert len(errors) == 1
        assert "columns must be a list of column names" in errors[0].message

    def test_scalar_rows_field_reports_error_not_crash(self) -> None:
        table = TableElement(id="sr", columns=["A"], rows=5)  # type: ignore[arg-type]  # deliberately malformed
        errors = table.validate()
        assert len(errors) == 1
        assert "rows must be a list of rows" in errors[0].message

    def test_scalar_columns_field_reports_error_not_crash(self) -> None:
        table = TableElement(id="sc", columns=3, rows=[["x"]])  # type: ignore[arg-type]  # deliberately malformed
        errors = table.validate()
        assert len(errors) == 1
        assert "columns must be a list of column names" in errors[0].message


class TestGroupChildElements:
    def test_visible_children_are_exposed(self) -> None:
        child = TableElement(id="t", columns=["A"], rows=[["x"]])
        group = GroupElement(id="g", children=[child])
        assert group.child_elements() == (child,)

    def test_paged_children_are_exposed(self) -> None:
        nav = TableElement(id="nav", columns=["A"], rows=[["x"]])
        paged = TableElement(id="paged", columns=["B"], rows=[["y"]])
        group = GroupElement(id="g", children=[nav], pages=[[paged]])
        assert group.child_elements() == (nav, paged)

    def test_empty_group_has_no_children(self) -> None:
        assert GroupElement(id="g").child_elements() == ()
