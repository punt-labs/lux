"""TableSelectionModel — per-mode cardinality, anchor reseat, reconcile, pickle."""

from __future__ import annotations

import copy

from punt_lux.protocol.elements.table_selection_model import TableSelectionModel


class TestNoneMode:
    def test_construction_is_empty(self) -> None:
        model = TableSelectionModel(mode="none", selected=frozenset({"a"}), anchor="a")
        assert model.selected_row_ids == frozenset()
        assert model.anchor == ""
        assert model.is_selectable is False

    def test_apply_stays_empty(self) -> None:
        model = TableSelectionModel(mode="none")
        model.apply(frozenset({"a", "b"}), anchor="a")
        assert model.selected_row_ids == frozenset()
        assert model.anchor == ""


class TestSingleMode:
    def test_apply_keeps_only_the_anchor(self) -> None:
        model = TableSelectionModel(mode="single")
        model.apply(frozenset({"a", "b", "c"}), anchor="b")
        assert model.selected_row_ids == frozenset({"b"})
        assert model.anchor == "b"

    def test_apply_without_anchor_keeps_one(self) -> None:
        model = TableSelectionModel(mode="single")
        model.apply(frozenset({"a", "b", "c"}), anchor="")
        assert model.selected_row_ids == frozenset({"a"})  # min for determinism
        assert model.anchor == "a"

    def test_is_selectable(self) -> None:
        assert TableSelectionModel(mode="single").is_selectable is True


class TestMultiMode:
    def test_apply_keeps_the_whole_set(self) -> None:
        model = TableSelectionModel(mode="multi")
        model.apply(frozenset({"a", "b", "c"}), anchor="c")
        assert model.selected_row_ids == frozenset({"a", "b", "c"})
        assert model.anchor == "c"

    def test_anchor_outside_the_set_is_reseated(self) -> None:
        model = TableSelectionModel(mode="multi")
        model.apply(frozenset({"a", "b"}), anchor="z")
        assert model.anchor == "a"  # reseated to the min selected id

    def test_empty_selection_clears_the_anchor(self) -> None:
        model = TableSelectionModel(mode="multi")
        model.apply(frozenset(), anchor="a")
        assert model.selected_row_ids == frozenset()
        assert model.anchor == ""


class TestReconcile:
    def test_drops_departed_ids(self) -> None:
        model = TableSelectionModel(mode="multi", selected=frozenset({"a", "b", "c"}))
        model.reconcile(frozenset({"a", "c"}))
        assert model.selected_row_ids == frozenset({"a", "c"})

    def test_departed_anchor_reseats_to_a_survivor(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b"}), anchor="b"
        )
        model.reconcile(frozenset({"a"}))
        assert model.selected_row_ids == frozenset({"a"})
        assert model.anchor == "a"

    def test_all_departed_clears_the_anchor(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b"}), anchor="a"
        )
        model.reconcile(frozenset({"z"}))
        assert model.selected_row_ids == frozenset()
        assert model.anchor == ""


class TestSerialization:
    def test_survives_a_reduce_setstate_roundtrip(self) -> None:
        # copy.deepcopy drives __reduce__ / __setstate__ — the same path the
        # Hub-to-Display pickle transport uses — without loading foreign bytes.
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b"}), anchor="b"
        )
        restored = copy.deepcopy(model)
        assert restored.mode == "multi"
        assert restored.selected_row_ids == frozenset({"a", "b"})
        assert restored.anchor == "b"
