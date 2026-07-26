"""TableSelectionModel — raw construction, immutable per-mode verbs, serialize."""

from __future__ import annotations

import copy

from punt_lux.protocol.elements.table_selection_model import TableSelectionModel


class TestConstructionIsRaw:
    def test_holds_the_state_verbatim_for_the_validate_gate(self) -> None:
        # Construction must NOT normalize — validate() is the decode gate, so a
        # single-mode-with-two-ids selection has to survive to be reported.
        model = TableSelectionModel(
            mode="single", selected=frozenset({"a", "b"}), anchor="a"
        )
        assert model.selected_row_ids == frozenset({"a", "b"})
        assert model.anchor == "a"

    def test_is_selectable_reflects_mode(self) -> None:
        assert TableSelectionModel(mode="none").is_selectable is False
        assert TableSelectionModel(mode="single").is_selectable is True
        assert TableSelectionModel(mode="multi").is_selectable is True


class TestWithSelection:
    def test_returns_a_new_instance_leaving_the_original_untouched(self) -> None:
        # Immutability is what keeps apply_patch's rollback honest.
        original = TableSelectionModel(mode="multi")
        updated = original.with_selection(frozenset({"a", "b"}))
        assert updated is not original
        assert original.selected_row_ids == frozenset()
        assert updated.selected_row_ids == frozenset({"a", "b"})

    def test_none_mode_stays_empty(self) -> None:
        model = TableSelectionModel(mode="none").with_selection(frozenset({"a", "b"}))
        assert model.selected_row_ids == frozenset()
        assert model.anchor == ""

    def test_single_mode_keeps_one(self) -> None:
        model = TableSelectionModel(mode="single").with_selection(
            frozenset({"a", "b", "c"})
        )
        assert len(model.selected_row_ids) == 1

    def test_multi_mode_keeps_the_whole_set(self) -> None:
        model = TableSelectionModel(mode="multi").with_selection(
            frozenset({"a", "b", "c"})
        )
        assert model.selected_row_ids == frozenset({"a", "b", "c"})

    def test_anchor_reseats_onto_a_selected_row(self) -> None:
        model = TableSelectionModel(mode="multi", anchor="z").with_selection(
            frozenset({"a", "b"})
        )
        assert model.anchor == "a"  # reseated to the min selected id


class TestWithAnchor:
    def test_keeps_an_anchor_inside_the_selection(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b", "c"})
        ).with_anchor("c")
        assert model.anchor == "c"

    def test_drops_an_anchor_outside_the_selection(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b"})
        ).with_anchor("z")
        assert model.anchor == "a"  # reseated to a selected row


class TestReconciled:
    def test_drops_departed_ids(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b", "c"})
        ).reconciled(frozenset({"a", "c"}))
        assert model.selected_row_ids == frozenset({"a", "c"})

    def test_departed_anchor_reseats_to_a_survivor(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b"}), anchor="b"
        ).reconciled(frozenset({"a"}))
        assert model.selected_row_ids == frozenset({"a"})
        assert model.anchor == "a"

    def test_all_departed_clears_the_anchor(self) -> None:
        model = TableSelectionModel(
            mode="multi", selected=frozenset({"a", "b"}), anchor="a"
        ).reconciled(frozenset({"z"}))
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
