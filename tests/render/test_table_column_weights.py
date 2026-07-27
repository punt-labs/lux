"""ColumnWeights — content-proportioned stretch weights, pure logic.

No ImGui frame is needed: the weight computation is pure, so its clamping,
header-vs-cell max, ragged-row handling, and sample bound are pinned here.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.table_column_weights import ColumnWeights


def test_wider_content_gets_a_larger_weight() -> None:
    columns = ("ID", "Title")
    rows: tuple[tuple[object, ...], ...] = (
        ("1", "a long descriptive title"),
        ("2", "short"),
    )
    id_weight, title_weight = ColumnWeights().for_content(columns, rows)
    assert title_weight > id_weight


def test_weight_counts_the_header_when_it_is_widest() -> None:
    # The header "Status" (6) is wider than its one-char cells, so it sets the weight.
    columns = ("Status",)
    rows: tuple[tuple[object, ...], ...] = (("x",), ("y",))
    (weight,) = ColumnWeights().for_content(columns, rows)
    assert weight == 6.0


def test_short_content_clamps_up_to_the_minimum() -> None:
    columns = ("N",)  # header len 1, cells len 1 -> below the floor
    rows: tuple[tuple[object, ...], ...] = (("1",), ("2",))
    (weight,) = ColumnWeights().for_content(columns, rows)
    assert weight == 4.0  # _MIN_WEIGHT


def test_long_content_clamps_down_to_the_maximum() -> None:
    columns = ("Body",)
    rows: tuple[tuple[object, ...], ...] = (("x" * 200,),)
    (weight,) = ColumnWeights().for_content(columns, rows)
    assert weight == 40.0  # _MAX_WEIGHT


def test_non_string_cells_are_measured_as_text() -> None:
    # A number/None is measured by its str() length: str(None) is 4, str(12345) is 5.
    columns = ("V",)
    rows: tuple[tuple[object, ...], ...] = ((None,), (12345,))
    (weight,) = ColumnWeights().for_content(columns, rows)
    assert weight == 5.0  # len("12345"), clamped within range


def test_ragged_row_shorter_than_the_column_contributes_nothing() -> None:
    columns = ("A", "B")
    rows: tuple[tuple[object, ...], ...] = (("aaaa",),)  # no column-1 cell
    a_weight, b_weight = ColumnWeights().for_content(columns, rows)
    assert a_weight == 4.0  # "aaaa"
    assert b_weight == 4.0  # only header "B" (len 1) -> clamped to the floor


def test_one_weight_per_column_including_empty_rows() -> None:
    columns = ("A", "B", "C")
    assert len(ColumnWeights().for_content(columns, ())) == 3


def test_only_the_row_sample_is_scanned() -> None:
    # A wide value past the sample bound (row 200+) does not widen the column.
    columns = ("V",)
    rows: tuple[tuple[object, ...], ...] = (
        *(("x",) for _ in range(200)),
        ("y" * 30,),
    )
    (weight,) = ColumnWeights().for_content(columns, rows)
    assert weight == 4.0  # the wide row is beyond _SAMPLE_ROWS, so it is unseen
