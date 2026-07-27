"""TableSort — pure ordering semantics, no ImGui frame required.

TableSort is the real Display-local reorder the legacy ``sortable`` flag lacked;
it is pure logic and user-visible, so its ordering contract is pinned here:
per-direction asc/desc, multi-column stability, the total-order key over mixed
cell types (which avoids the comparison crash), out-of-range no-ops, and the
empty-specs identity.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.table_sort import TableSort

type _Pair = tuple[str, tuple[object, ...]]


def _ids(pairs: list[_Pair]) -> list[str]:
    return [pid for pid, _ in pairs]


def test_ascending_orders_by_the_cell_value() -> None:
    pairs: list[_Pair] = [("a", (3,)), ("b", (1,)), ("c", (2,))]
    assert _ids(TableSort().order(pairs, ((0, True),))) == ["b", "c", "a"]


def test_descending_reverses_the_direction() -> None:
    pairs: list[_Pair] = [("a", (3,)), ("b", (1,)), ("c", (2,))]
    assert _ids(TableSort().order(pairs, ((0, False),))) == ["a", "c", "b"]


def test_multi_column_sorts_by_primary_then_secondary() -> None:
    # Specs are (primary, secondary); the secondary breaks ties within the primary.
    pairs: list[_Pair] = [
        ("r1", ("b", "2")),
        ("r2", ("a", "1")),
        ("r3", ("b", "1")),
        ("r4", ("a", "2")),
    ]
    specs = ((0, True), (1, True))
    assert _ids(TableSort().order(pairs, specs)) == ["r2", "r4", "r3", "r1"]


def test_equal_keys_keep_prior_order_stable() -> None:
    # Rows identical in every sorted column keep their input order (stable sort).
    pairs: list[_Pair] = [
        ("first", ("a", "x")),
        ("second", ("a", "x")),
        ("third", ("a", "w")),
    ]
    specs = ((0, True), (1, True))
    # col0 all "a"; col1 orders "w" before "x"; the two "x" rows keep first<second.
    assert _ids(TableSort().order(pairs, specs)) == ["third", "first", "second"]


def test_heterogeneous_column_orders_null_then_number_then_string() -> None:
    # The total-order key groups mixed cells (null < number < string) so the sort
    # never raises comparing str to int; ascending pins the exact order.
    pairs: list[_Pair] = [
        ("s", ("abc",)),
        ("n5", (5,)),
        ("none", (None,)),
        ("n2", (2,)),
    ]
    ordered = _ids(TableSort().order(pairs, ((0, True),)))
    assert ordered == ["none", "n2", "n5", "s"]


def test_heterogeneous_column_descending_reverses_the_total_order() -> None:
    pairs: list[_Pair] = [
        ("s", ("abc",)),
        ("n5", (5,)),
        ("none", (None,)),
        ("n2", (2,)),
    ]
    ordered = _ids(TableSort().order(pairs, ((0, False),)))
    assert ordered == ["s", "n5", "n2", "none"]


def test_out_of_range_column_is_a_no_op() -> None:
    # Every row keys to the same null-group value, so a stable sort leaves the
    # input order untouched.
    pairs: list[_Pair] = [("a", ("x",)), ("b", ("y",)), ("c", ("z",))]
    assert _ids(TableSort().order(pairs, ((5, True),))) == ["a", "b", "c"]


def test_empty_specs_return_the_pairs_unchanged() -> None:
    pairs: list[_Pair] = [("a", (3,)), ("b", (1,)), ("c", (2,))]
    result = TableSort().order(pairs, ())
    assert _ids(result) == ["a", "b", "c"]
    assert result is not pairs  # a fresh list, not the caller's
