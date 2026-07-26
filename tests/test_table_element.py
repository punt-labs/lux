"""Migration gate for the ABC ``table`` element — the basic data grid.

Levels 1-2 per ``tests/CLAUDE.md`` (serialization + wire roundtrip), self-
validation (DES-039), the built-in selection state-sync, and introspection. The
filter/detail composition lives in ``test_table_composition.py``.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from punt_lux.display_client import agent_element_factory
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.scene import SceneMessage


def _decode(wire: dict[str, Any]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(wire)


def _errors(table: TableElement) -> tuple[object, ...]:
    """Return the validation errors the tree walk collects for ``table``."""
    return ElementTreeValidator().validate_tree([table]).errors


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_basic_grid_roundtrips_to_abc(self) -> None:
        table = TableElement(
            id="t", columns=("Name", "Score"), rows=(("Alice", 95), ("Bob", 87))
        )
        restored = _decode(table.to_dict())
        assert isinstance(restored, TableElement)
        assert list(restored.columns) == ["Name", "Score"]
        assert restored.rows == (("Alice", 95), ("Bob", 87))
        assert restored.selection_mode == "none"

    @pytest.mark.parametrize("mode", ["none", "single", "multi"])
    def test_each_selection_mode_roundtrips(self, mode: str) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode=cast("Any", mode),
        )
        restored = _decode(table.to_dict())
        assert isinstance(restored, TableElement)
        assert restored.selection_mode == mode

    def test_key_column_as_index_roundtrips(self) -> None:
        table = TableElement(
            id="t", columns=("ID", "V"), rows=(("a", 1),), key_column=1
        )
        restored = _decode(table.to_dict())
        assert isinstance(restored, TableElement)
        assert restored.key_column == 1

    def test_key_column_as_name_resolves_to_index(self) -> None:
        restored = _decode(
            {"kind": "table", "id": "t", "columns": ["ID", "V"], "key_column": "V"}
        )
        assert isinstance(restored, TableElement)
        assert restored.key_column == 1

    def test_key_column_absent_name_is_rejected_naming_it(self) -> None:
        # A name that matches no column is a wire error naming the name — never a
        # silent -1 the agent later sees echoed in a validate message.
        with pytest.raises(ValueError, match="does not name a column"):
            _decode(
                {"kind": "table", "id": "t", "columns": ["ID"], "key_column": "Nope"}
            )

    def test_column_widths_reject_a_non_finite_value_naming_the_index(self) -> None:
        # A non-finite stretch weight (nan/inf) into table_setup_column is
        # undefined behavior — the wire boundary rejects it, naming the index.
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match=r"column_widths\[1\] must be finite"):
                _decode(
                    {
                        "kind": "table",
                        "id": "t",
                        "columns": ["A", "B"],
                        "rows": [["x", "y"]],
                        "column_widths": [1.0, bad],
                    }
                )

    def test_flags_and_selection_survive(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            flags=TableFlags(borders=True, sortable=True, row_bg=False),
            selection_mode="multi",
            selected_row_ids=frozenset({"a"}),
            anchor_row_id="a",
        )
        restored = _decode(table.to_dict())
        assert isinstance(restored, TableElement)
        assert restored.flags == TableFlags(borders=True, sortable=True, row_bg=False)
        assert restored.selected_row_ids == frozenset({"a"})
        assert restored.anchor_row_id == "a"

    def test_nested_in_group_roundtrips(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "children": [
                TableElement(id="t", columns=("A",), rows=(("x",),)).to_dict()
            ],
        }
        restored = _decode(wire)
        assert type(restored).__name__ == "GroupElement"

    def test_scroll_reserve_lines_survives_the_roundtrip(self) -> None:
        table = TableElement(
            id="t", columns=("ID",), rows=(("a",),), scroll_reserve_lines=8
        )
        restored = _decode(table.to_dict())
        assert isinstance(restored, TableElement)
        assert restored.scroll_reserve_lines == 8

    def test_scroll_reserve_lines_defaults_to_zero(self) -> None:
        restored = _decode(
            {"kind": "table", "id": "t", "columns": ["ID"], "rows": [["a"]]}
        )
        assert isinstance(restored, TableElement)
        assert restored.scroll_reserve_lines == 0


# -- Self-validation (DES-039) ----------------------------------------------


class TestValidate:
    def test_display_only_grid_with_repeated_key_is_valid(self) -> None:
        # mode "none": no key-column constraint — a status/count aggregate is fine.
        table = TableElement(
            id="agg", columns=("Status", "N"), rows=(("open", 3), ("open", 1))
        )
        assert table.validate() == ()

    def test_bool_cell_is_a_valid_scalar(self) -> None:
        # A boolean cell is an accepted scalar (the error message lists "boolean");
        # _SCALAR names bool explicitly so the contract is self-evident.
        table = TableElement(id="t", columns=("Name", "Active"), rows=(("x", True),))
        assert table.validate() == ()

    def test_selectable_duplicate_key_is_rejected(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("a",)),
            selection_mode="multi",
        )
        errors = table.validate()
        assert any("duplicate key" in e.message for e in errors)

    def test_selectable_empty_key_is_rejected(self) -> None:
        table = TableElement(
            id="t", columns=("ID",), rows=(("",),), selection_mode="single"
        )
        assert any("empty key" in e.message for e in table.validate())

    def test_single_select_with_two_ids_is_rejected(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="single",
            selected_row_ids=frozenset({"a", "b"}),
        )
        assert any("more than one" in e.message for e in table.validate())

    def test_selected_id_naming_no_row_is_rejected(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",),),
            selection_mode="multi",
            selected_row_ids=frozenset({"z"}),
        )
        assert any("names no row" in e.message for e in table.validate())

    def test_key_column_out_of_range_is_rejected_when_selectable(self) -> None:
        table = TableElement(
            id="t",
            columns=("A",),
            rows=(("x",),),
            key_column=5,
            selection_mode="single",
        )
        assert any("names no column" in e.message for e in table.validate())

    def test_structural_guard_table_is_a_leaf(self) -> None:
        table = TableElement(id="t", columns=("A",), rows=(("x",),))
        assert table.child_elements() == ()

    def test_nested_invalid_table_is_collected_by_the_walk(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("a",)),
            selection_mode="multi",
        )
        assert _errors(table)  # the walk surfaces the duplicate-key error


# -- Level 2: wire roundtrip -------------------------------------------------


class TestLevel2Wire:
    def test_table_crosses_as_pickled_entry(self) -> None:
        # Decode first so the built-in state-sync handler is installed (the
        # decoder's job), then cross the wire.
        table = _decode(
            {
                "kind": "table",
                "id": "t",
                "columns": ["ID"],
                "rows": [["a"], ["b"]],
                "selection_mode": "multi",
                "selected_row_ids": ["a"],
            }
        )
        assert isinstance(table, TableElement)
        scene = SceneMessage(id="s1", elements=[table], frame_id="s1")
        restored = message_from_dict(message_to_dict(scene))
        assert isinstance(restored, SceneMessage)
        table2 = restored.elements[0]
        assert isinstance(table2, TableElement)
        assert table2.selected_row_ids == frozenset({"a"})
        # The built-in state-sync handler survived the pickle.
        assert table2.handler_count(RowSelectionChanged) == 1


# -- built-in selection state-sync + introspection --------------------------


class TestSelectionSyncAndIntrospection:
    def test_built_in_handler_mirrors_the_selection(self) -> None:
        table = _decode(
            {
                "kind": "table",
                "id": "t",
                "columns": ["ID"],
                "rows": [["a"], ["b"], ["c"]],
                "selection_mode": "multi",
            }
        )
        assert isinstance(table, TableElement)
        table.fire(
            RowSelectionChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("t"),
                owner_id=ClientId("c"),
                row_ids=("a", "c"),
                anchor="c",
            )
        )
        assert table.selected_row_ids == frozenset({"a", "c"})
        assert table.anchor_row_id == "c"

    def test_reconcile_keeps_selection_across_a_reorder(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",), ("c",)),
            selection_mode="multi",
            selected_row_ids=frozenset({"a", "c"}),
        )
        table.apply_patch({"rows": [["c"], ["a"]]})  # b removed, reordered
        assert table.selected_row_ids == frozenset({"a", "c"})

    def test_resolved_props_reports_selection_state(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",),),
            selection_mode="single",
            selected_row_ids=frozenset({"a"}),
            anchor_row_id="a",
        )
        props = table.resolved_props()
        assert props["selection_mode"] == "single"
        assert props["selected_row_ids"] == ["a"]
        assert props["anchor_row_id"] == "a"
        assert props["row_count"] == 1


class TestModeNoneCarriesNoSelectionMachinery:
    """A display-only grid ships zero selection machinery (the reviewer's #2).

    A ``none``-mode table routes to the plain renderer, so installing a state-sync
    handler and advertising a remote-dispatch bucket are pure overhead that also
    makes a plain grid *look* interactive in introspection. Both are gated off.
    """

    def test_none_mode_grid_advertises_no_remote_dispatch(self) -> None:
        grid = TableElement(id="t", columns=("ID",), rows=(("a",),))
        assert grid.selection_mode == "none"
        assert grid._remote_dispatch_specs() == ()

    def test_selectable_grid_still_advertises_its_bucket(self) -> None:
        grid = TableElement(
            id="t", columns=("ID",), rows=(("a",),), selection_mode="single"
        )
        specs = grid._remote_dispatch_specs()
        assert len(specs) == 1
        assert specs[0].event_kind == "row_selection_changed"

    def test_none_mode_decode_installs_no_state_sync_handler(self) -> None:
        grid = _decode({"kind": "table", "id": "t", "columns": ["ID"], "rows": [["a"]]})
        assert isinstance(grid, TableElement)
        assert grid.handler_count(RowSelectionChanged) == 0

    def test_selectable_decode_installs_the_state_sync_handler(self) -> None:
        grid = _decode(
            {
                "kind": "table",
                "id": "t",
                "columns": ["ID"],
                "rows": [["a"]],
                "selection_mode": "multi",
            }
        )
        assert isinstance(grid, TableElement)
        assert grid.handler_count(RowSelectionChanged) == 1


class TestPatchAtomicity:
    def test_a_failed_multi_key_patch_rolls_back_the_selection(self) -> None:
        # apply_patch is all-or-nothing: a patch that mutates rows (reconciling
        # the selection) then fails on a later key must restore the ORIGINAL
        # selection, not the half-reconciled one. The immutable selection model
        # is what makes the shallow vars() rollback cover the composed state.
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="multi",
            selected_row_ids=frozenset({"a", "b"}),
        )
        with pytest.raises(ValueError, match="flags must be a list"):
            # rows would drop "b" from the selection; flags then fails and rolls back.
            table.apply_patch({"rows": [["a"]], "flags": "not-a-list"})
        assert table.rows == (("a",), ("b",))
        assert table.selected_row_ids == frozenset({"a", "b"})

    def test_selected_ids_are_reconciled_against_live_rows(self) -> None:
        # A ghost id (racing a rows re-push) must never land in the authority —
        # the renderer's fire-if-changed would read it back as a spurious change.
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="multi",
        )
        table.apply_patch({"selected_row_ids": ["a", "ghost"]})
        assert table.selected_row_ids == frozenset({"a"})

    def test_bad_selection_patch_names_the_public_field(self) -> None:
        # The error must name the public field ``selected_row_ids``, not the
        # internal shorthand, so an agent's fix targets the right key.
        table = TableElement(
            id="t", columns=("ID",), rows=(("a",),), selection_mode="multi"
        )
        with pytest.raises(ValueError, match="selected_row_ids must be a list"):
            table.apply_patch({"selected_row_ids": 123})


class TestRowsReconcileNotifiesObservers:
    """A rows patch notifies ``rows``; a reconcile that changes the selection also
    notifies ``selected_row_ids``.

    A rows write always notifies ``rows`` so a bound FilteredTableModel can absorb
    a dataset refresh; when the reconcile drops a row or reseats the anchor, the
    ``selected_row_ids`` signal is queued too (deferred to commit), so the model
    and detail do not go stale. An unchanged selection adds no selection signal.
    """

    def test_rows_patch_dropping_the_selection_notifies_rows_and_selection(
        self,
    ) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="multi",
            selected_row_ids=frozenset({"a"}),
            anchor_row_id="a",
        )
        seen: list[str] = []
        table.add_observer(seen.append)
        table.apply_patch({"rows": [["b"]]})  # drops a
        assert table.selected_row_ids == frozenset()
        assert seen == ["rows", "selected_row_ids"]  # both, once each, at commit

    def test_rows_patch_keeping_the_selection_notifies_only_rows(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="multi",
            selected_row_ids=frozenset({"a"}),
            anchor_row_id="a",
        )
        seen: list[str] = []
        table.add_observer(seen.append)
        table.apply_patch({"rows": [["a"], ["b"], ["c"]]})  # a survives, anchor a stays
        assert table.selected_row_ids == frozenset({"a"})
        assert seen == ["rows"]  # dataset signal only; selection unchanged

    def test_anchor_only_patch_notifies_observers(self) -> None:
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="single",
            selected_row_ids=frozenset({"a"}),
            anchor_row_id="a",
        )
        seen: list[str] = []
        table.add_observer(seen.append)
        table.apply_patch({"anchor_row_id": "a"})
        assert seen == ["selected_row_ids"]

    def test_selection_and_anchor_patch_notifies_once(self) -> None:
        # Both setters queue "selected_row_ids"; the commit buffer de-dups, so a
        # patch touching selection and anchor fires the observer exactly once.
        table = TableElement(
            id="t", columns=("ID",), rows=(("a",),), selection_mode="single"
        )
        seen: list[str] = []
        table.add_observer(seen.append)
        table.apply_patch({"selected_row_ids": ["a"], "anchor_row_id": "a"})
        assert seen == ["selected_row_ids"]
