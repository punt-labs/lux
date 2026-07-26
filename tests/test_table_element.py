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


# -- Self-validation (DES-039) ----------------------------------------------


class TestValidate:
    def test_display_only_grid_with_repeated_key_is_valid(self) -> None:
        # mode "none": no key-column constraint — a status/count aggregate is fine.
        table = TableElement(
            id="agg", columns=("Status", "N"), rows=(("open", 3), ("open", 1))
        )
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
