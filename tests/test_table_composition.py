"""The show_table composition — builder shape plus Hub-side filter/detail behavior.

The composition is built as element instances and installed as objects; these
tests drive its handlers in-process (the same handlers the Hub fires on a crossed
interaction) to prove the Hub-side filter, the selection-authority blocker fix,
and the detail binding. Level-6 confirms the live rendering.
"""

from __future__ import annotations

import copy

import pytest

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.compositions import (
    FilteredTableModel,
    TableComposition,
    TableCompositionSpec,
)
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.table import TableElement

_SCENE = SceneId("s")
_OWNER = ClientId("c")


def _select(table: TableElement, *row_ids: str, anchor: str = "") -> None:
    """Fire a row-selection gesture on ``table``'s handlers."""
    table.fire(
        RowSelectionChanged(
            scene_id=_SCENE,
            element_id=ElementId(table.id),
            owner_id=_OWNER,
            row_ids=row_ids,
            anchor=anchor or (row_ids[-1] if row_ids else ""),
        )
    )


def _change(element: object, value: bool | int | float | str) -> None:
    """Fire a value-changed gesture on ``element``'s handlers."""
    assert isinstance(element, (InputTextElement, ComboElement))
    element.fire(
        ValueChanged(
            scene_id=_SCENE,
            element_id=ElementId(element.id),
            owner_id=_OWNER,
            value=value,
        )
    )


def _table(group: GroupElement) -> TableElement:
    return next(c for c in group.children if isinstance(c, TableElement))


def _combo(group: GroupElement) -> ComboElement:
    return next(c for c in group.children if isinstance(c, ComboElement))


def _search(group: GroupElement) -> InputTextElement:
    return next(c for c in group.children if isinstance(c, InputTextElement))


class TestScrollReserve:
    def test_a_grid_without_a_detail_reserves_nothing(self) -> None:
        from punt_lux.protocol.compositions.table_composition import (
            _detail_reserve_lines,
        )

        assert _detail_reserve_lines(None) == 0

    def test_reserve_is_proportioned_to_the_field_count_and_clamped(self) -> None:
        from punt_lux.protocol.compositions.table_composition import (
            _detail_reserve_lines,
        )

        assert _detail_reserve_lines({"fields": []}) == 6  # clamped up to the min
        assert _detail_reserve_lines({"fields": ["a", "b", "c", "d", "e"]}) == 9
        assert _detail_reserve_lines({"fields": list("abcdefghijklmnop")}) == 16  # max


class TestBuilderShape:
    def test_no_chrome_returns_the_bare_grid(self) -> None:
        roots = TableComposition.build(
            TableCompositionSpec(columns=("A",), rows=(("x",),))
        )
        assert len(roots) == 1
        assert isinstance(roots[0], TableElement)
        assert roots[0].selection_mode == "none"
        assert roots[0].scroll_reserve_lines == 0  # no detail -> no reserve

    def test_chrome_composes_one_group_root(self) -> None:
        roots = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Status"),
                rows=(("1", "open"),),
                filters=({"type": "search", "column": [0]},),
                detail={"fields": ["ID"], "rows": [["1"]], "body": ["b"]},
            )
        )
        assert len(roots) == 1
        group = roots[0]
        assert isinstance(group, GroupElement)
        assert [type(c).__name__ for c in group.children] == [
            "InputTextElement",
            "TableElement",
            "MarkdownElement",
        ]
        assert _table(group).selection_mode == "single"  # detail -> single

    def test_table_id_seeds_the_synthesized_ids_so_two_tables_coexist(self) -> None:
        # Two show_table compositions in one scene must not collide: a distinct
        # table_id prefixes the group root, the grid, and every control id.
        def group_for(table_id: str) -> GroupElement:
            roots = TableComposition.build(
                TableCompositionSpec(
                    columns=("ID",),
                    rows=(("1",),),
                    filters=({"type": "search", "column": [0]},),
                    table_id=table_id,
                )
            )
            root = roots[0]
            assert isinstance(root, GroupElement)
            return root

        left, right = group_for("left"), group_for("right")
        assert left.id == "left-view"
        assert right.id == "right-view"
        left_ids = {left.id, *(c.id for c in left.children)}
        right_ids = {right.id, *(c.id for c in right.children)}
        assert left_ids.isdisjoint(right_ids), "no synthesized id may collide"


class TestHubSideFiltering:
    def _explorer(self) -> GroupElement:
        roots = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Status"),
                rows=(("a", "open"), ("b", "closed"), ("c", "open"), ("d", "closed")),
                filters=(
                    {"type": "search", "column": [0]},
                    {
                        "type": "combo",
                        "column": 1,
                        "items": ["All", "open", "closed"],
                        "label": "Status",
                    },
                ),
            )
        )
        group = roots[0]
        assert isinstance(group, GroupElement)
        return group

    def test_search_input_is_the_autofocus_target(self) -> None:
        # PR #283 polish: the composed search is the keyboard-focus target so the
        # user can type immediately; other scenes' inputs stay autofocus=False.
        assert _search(self._explorer()).autofocus is True

    def test_search_filters_hub_side(self) -> None:
        group = self._explorer()
        _change(_search(group), "c")
        assert [row[0] for row in _table(group).rows] == ["c"]

    def test_combo_filters_hub_side(self) -> None:
        group = self._explorer()
        _change(_combo(group), 2)  # "closed"
        assert [row[0] for row in _table(group).rows] == ["b", "d"]

    def test_filter_hides_then_restores_a_hidden_selection(self) -> None:
        # The selection-authority blocker: a selected row hidden by a filter is
        # kept in the full selection and reappears when the filter is cleared.
        group = self._explorer()
        table = _table(group)
        _select(table, "a", "d", anchor="d")
        assert table.selected_row_ids == frozenset({"a", "d"})
        _change(_combo(group), 1)  # "open" -> only a, c visible; d hidden
        assert [row[0] for row in table.rows] == ["a", "c"]
        assert table.selected_row_ids == frozenset({"a"})  # d is hidden
        _change(_combo(group), 0)  # "All" -> clear
        assert [row[0] for row in table.rows] == ["a", "b", "c", "d"]
        assert table.selected_row_ids == frozenset({"a", "d"})  # restored

    def test_still_matching_selection_stays_selected_under_search(self) -> None:
        group = self._explorer()
        table = _table(group)
        _select(table, "a", anchor="a")
        _change(_search(group), "a")  # only row a matches
        assert [row[0] for row in table.rows] == ["a"]
        assert table.selected_row_ids == frozenset({"a"})

    def test_agent_selection_under_a_filter_writes_through_to_the_model(self) -> None:
        # PR #283 MEDIUM: an agent apply_patch of selected_row_ids (not a gesture)
        # must reach the model's full selection, or the next re-projection shadows
        # it. Select d (all visible), filter it out, then agent-select a visible
        # row; clearing the filter must restore BOTH the agent's pick and d.
        group = self._explorer()
        table = _table(group)
        _select(table, "d", anchor="d")  # d selected while everything is visible
        _change(_combo(group), 1)  # "open" -> a, c visible; d hidden
        assert table.selected_row_ids == frozenset()  # d hidden
        table.apply_patch({"selected_row_ids": ["a"]})  # AGENT write, not a gesture
        _change(_combo(group), 0)  # "All" -> clear the filter
        assert table.selected_row_ids == frozenset({"a", "d"})  # both restored

    def test_agent_rows_patch_refreshes_the_dataset_under_a_filter(self) -> None:
        # PR #283 HIGH (rows analog): an agent apply_patch of rows (the refresh
        # path) becomes the new dataset; the active filter re-applies to it, and a
        # later filter change uses the NEW dataset, not the stale snapshot.
        group = self._explorer()
        table = _table(group)
        _change(_combo(group), 1)  # "open" -> a, c visible
        assert [row[0] for row in table.rows] == ["a", "c"]
        table.apply_patch({"rows": [["e", "open"], ["f", "closed"]]})  # AGENT refresh
        assert [row[0] for row in table.rows] == ["e"]  # filter re-applied to new data
        _change(_combo(group), 0)  # "All" -> the NEW dataset, not old {a,b,c,d}
        assert [row[0] for row in table.rows] == ["e", "f"]

    def test_the_models_own_reprojection_keeps_the_dataset(self) -> None:
        # The self-write guard: the model's re-projection writes the filtered
        # subset, which must NOT be folded back in as the dataset — clearing the
        # filter restores every row.
        group = self._explorer()
        table = _table(group)
        _change(_combo(group), 1)  # "open" -> filtered subset a, c
        _change(_combo(group), 0)  # "All"
        assert [row[0] for row in table.rows] == ["a", "b", "c", "d"]

    def test_agent_rows_patch_reconciles_the_full_selection(self) -> None:
        # A dataset change (unlike a filter) drops ids that vanished from the data
        # out of the full selection; survivors are kept.
        group = self._explorer()
        table = _table(group)
        _select(table, "a", "d", anchor="d")  # full selection {a, d}
        # Refresh the data: d is gone, a survives.
        table.apply_patch({"rows": [["a", "open"], ["e", "open"]]})
        assert table.selected_row_ids == frozenset({"a"})

    def test_dual_rows_and_selection_patch_keeps_the_selection(self) -> None:
        # PR #283 HIGH: one apply_patch that sets BOTH rows and selected_row_ids
        # must keep the patched selection — the rows notification's re-projection
        # must not clobber it by projecting off the stale full selection.
        group = self._explorer()
        table = _table(group)
        _change(_combo(group), 1)  # "open" filter active
        table.apply_patch(
            {"rows": [["e", "open"], ["f", "closed"]], "selected_row_ids": ["e"]}
        )
        assert [row[0] for row in table.rows] == ["e"]  # filter re-applied to new data
        assert table.selected_row_ids == frozenset({"e"})  # patched selection kept


class TestModelSeeding:
    def test_model_seeds_full_selection_from_the_table(self) -> None:
        # A grid built with a seeded selection (a rebuilt show_table) hands the
        # model a matching full selection, so the seed is not lost on the first
        # re-projection.
        table = TableElement(
            id="t",
            columns=("ID",),
            rows=(("a",), ("b",)),
            selection_mode="multi",
            selected_row_ids=frozenset({"a"}),
        )
        model = FilteredTableModel(
            all_rows=(("a",), ("b",)),
            key_column=0,
            search_columns=(),
            table=table,
        )
        assert model.full_selection == frozenset({"a"})


class TestWriteThroughAtomicity:
    """A patch that fails must not leave the observing model half-updated.

    The write-through folds a selection write into the model from inside the
    element's ``apply_patch``. If the notification fired eagerly, a later key
    failing would roll back the element but not the model, and a filter-clear
    could then restore a selection from a patch that reported failure (the F1
    atomicity class, one level up). ``apply_patch`` defers observer notification
    to commit, so a failed patch notifies nothing.
    """

    def _bound(self) -> tuple[TableElement, FilteredTableModel]:
        rows = (("a", "o"), ("b", "c"))
        table = TableElement(
            id="t", columns=("ID", "S"), rows=rows, selection_mode="multi"
        )
        model = FilteredTableModel(
            all_rows=rows, key_column=0, search_columns=(), table=table
        )
        return table, model

    def test_a_failed_multi_key_patch_leaves_the_model_unchanged(self) -> None:
        table, model = self._bound()
        assert model.full_selection == frozenset()
        # selected_row_ids succeeds, then columns fails (non-list) -> rollback.
        with pytest.raises(ValueError, match="columns must be a list"):
            table.apply_patch({"selected_row_ids": ["a"], "columns": 123})
        assert table.selected_row_ids == frozenset()  # element rolled back
        assert model.full_selection == frozenset()  # and the model with it

    def test_a_successful_patch_still_folds_through_to_the_model(self) -> None:
        table, model = self._bound()
        table.apply_patch({"selected_row_ids": ["a"]})
        assert table.selected_row_ids == frozenset({"a"})
        assert model.full_selection == frozenset({"a"})


class TestDetailBinding:
    def _master_detail(self) -> GroupElement:
        roots = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Title"),
                rows=(("a", "Alpha"), ("b", "Beta")),
                detail={
                    "fields": ["ID", "Title"],
                    "rows": [["a", "Alpha"], ["b", "Beta"]],
                    "body": ["about alpha", "about beta"],
                },
            )
        )
        group = roots[0]
        assert isinstance(group, GroupElement)
        return group

    def test_detail_binds_to_the_anchor_row(self) -> None:
        group = self._master_detail()
        detail = next(c for c in group.children if isinstance(c, MarkdownElement))
        _select(_table(group), "b", anchor="b")
        assert "about beta" in detail.content
        assert "**Title:** Beta" in detail.content

    def test_detail_starts_with_a_placeholder(self) -> None:
        group = self._master_detail()
        detail = next(c for c in group.children if isinstance(c, MarkdownElement))
        assert "Select a row" in detail.content

    def test_detail_reserves_scroll_space_on_the_grid(self) -> None:
        # PR #283 demo #1: with a detail below it, the grid reserves scroll space
        # so the detail is not pushed off the bottom of the frame.
        group = self._master_detail()
        assert _table(group).scroll_reserve_lines > 0

    def test_anchor_only_patch_re_drives_the_detail(self) -> None:
        # PR #283: an anchor-only agent patch must re-drive the detail through the
        # selection observer, not leave it stale until the next selection write.
        group = self._master_detail()
        table = _table(group)
        detail = next(c for c in group.children if isinstance(c, MarkdownElement))
        _select(table, "a", anchor="a")
        assert "about alpha" in detail.content
        detail.apply_patch({"content": "STALE"})  # force the detail out of sync
        table.apply_patch({"anchor_row_id": "a"})  # anchor-only write
        assert "about alpha" in detail.content
        assert "STALE" not in detail.content

    def test_rows_only_patch_dropping_the_anchor_re_drives_the_detail(self) -> None:
        # PR #283: a rows-only patch that reconciles away the selected/anchored row
        # must re-drive the detail (via the _set_rows reconcile notification), not
        # leave it showing the vanished row.
        group = self._master_detail()
        detail = next(c for c in group.children if isinstance(c, MarkdownElement))
        _select(_table(group), "a", anchor="a")
        assert "about alpha" in detail.content
        _table(group).apply_patch({"rows": [["b", "Beta"]]})  # drops row a
        assert "about alpha" not in detail.content
        assert "Select a row" in detail.content  # anchor cleared -> placeholder

    def test_agent_selection_patch_re_drives_the_detail(self) -> None:
        # PR #283 HIGH: an agent apply_patch of selected_row_ids (not a gesture,
        # no RowSelectionChanged) must re-drive the detail through the same path a
        # gesture and a filter re-projection use — the selection observer.
        group = self._master_detail()
        detail = next(c for c in group.children if isinstance(c, MarkdownElement))
        _select(_table(group), "a", anchor="a")
        assert "about alpha" in detail.content
        _table(group).apply_patch({"selected_row_ids": ["b"]})  # AGENT write
        assert "about beta" in detail.content
        assert "about alpha" not in detail.content

    def test_filtering_out_the_anchor_re_drives_the_detail(self) -> None:
        # A filter that hides the anchored row must not leave the panel showing
        # the vanished row's card (F6): _reproject re-drives the detail.
        group = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Status"),
                rows=(("a", "open"), ("b", "closed")),
                filters=(
                    {"type": "combo", "column": 1, "items": ["All", "open", "closed"]},
                ),
                detail={
                    "fields": ["ID"],
                    "rows": [["a"], ["b"]],
                    "body": ["about a", "about b"],
                },
            )
        )[0]
        assert isinstance(group, GroupElement)
        detail = next(c for c in group.children if isinstance(c, MarkdownElement))
        _select(_table(group), "a", anchor="a")
        assert "about a" in detail.content
        _change(_combo(group), 2)  # "closed" hides row a
        assert "about a" not in detail.content
        assert "Select a row" in detail.content  # reseated to placeholder


class TestFilterRobustness:
    def test_empty_table_id_is_rejected_at_the_builder(self) -> None:
        # PR #283: the invariant lives in build() too, so a direct caller can't
        # construct an anonymous composition (the "" element-id sentinel).
        with pytest.raises(ValueError, match="table_id must be a non-empty"):
            TableComposition.build(
                TableCompositionSpec(columns=("A",), rows=(("x",),), table_id="  ")
            )

    def test_search_with_name_columns_searches_all_columns(self) -> None:
        # A search whose "column" is names (not int indices) must not silently
        # empty the table — it falls back to searching every column (F3).
        group = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Title"),
                rows=(("1", "alpha"), ("2", "beta")),
                filters=({"type": "search", "column": ["Title"]},),
            )
        )[0]
        assert isinstance(group, GroupElement)
        _change(_search(group), "alpha")
        assert [row[0] for row in _table(group).rows] == ["1"]

    def test_search_all_out_of_range_columns_searches_all_columns(self) -> None:
        # PR #283: search indices all out of range must not fail closed — they
        # drop to () at build time, so the model falls open to every column.
        group = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Title"),
                rows=(("1", "alpha"), ("2", "beta")),
                filters=({"type": "search", "column": [5, 9]},),  # out of range
            )
        )[0]
        assert isinstance(group, GroupElement)
        _change(_search(group), "alpha")  # matched in Title via the fallback
        assert [row[0] for row in _table(group).rows] == ["1"]

    def test_unknown_filter_type_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown table filter type"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID",),
                    rows=(("a",),),
                    filters=({"type": "slider", "column": 0},),
                )
            )

    def test_combo_non_int_column_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be an int index"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID", "Status"),
                    rows=(("a", "open"),),
                    filters=({"type": "combo", "column": "Status", "items": ["All"]},),
                )
            )

    def test_combo_ignores_a_bool_value_as_no_selection(self) -> None:
        # PR #283: bool subclasses int, so ValueChanged(value=True) must not read
        # as index 1 ("open"); it falls back to no selection and leaves all rows.
        group = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Status"),
                rows=(("a", "open"), ("b", "closed")),
                filters=(
                    {"type": "combo", "column": 1, "items": ["All", "open", "closed"]},
                ),
            )
        )[0]
        assert isinstance(group, GroupElement)
        _change(_combo(group), True)  # a bool, not an index
        assert [row[0] for row in _table(group).rows] == ["a", "b"]

    def test_combo_out_of_range_column_is_rejected(self) -> None:
        # PR #283: an out-of-range combo column would empty the table the moment a
        # non-"All" value is picked. Range-check at construction with a named error.
        with pytest.raises(ValueError, match="out of range for 2 columns"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID", "Status"),
                    rows=(("a", "open"),),
                    filters=({"type": "combo", "column": 5, "items": ["All"]},),
                )
            )

    def test_empty_combo_items_is_rejected(self) -> None:
        # PR #283: an empty items list builds a choiceless control — fail loud,
        # matching the legacy TableFilter contract.
        with pytest.raises(ValueError, match="'items' must be a non-empty list"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID", "Status"),
                    rows=(("a", "open"),),
                    filters=({"type": "combo", "column": 1, "items": []},),
                )
            )

    def test_omitted_combo_items_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="'items' must be a non-empty list"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID", "Status"),
                    rows=(("a", "open"),),
                    filters=({"type": "combo", "column": 1},),  # items omitted
                )
            )

    def test_non_list_combo_items_is_rejected(self) -> None:
        # PR #283: an open wire shape can arrive as None/scalar — fail loud with
        # the field name, not a bare TypeError inside a comprehension.
        with pytest.raises(ValueError, match="combo filter 'items' must be a list"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID", "Status"),
                    rows=(("a", "open"),),
                    filters=({"type": "combo", "column": 1, "items": None},),
                )
            )

    def test_non_list_detail_fields_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="detail 'fields' must be a list"):
            TableComposition.build(
                TableCompositionSpec(
                    columns=("ID",),
                    rows=(("a",),),
                    detail={"fields": None, "rows": [["a"]], "body": ["x"]},
                )
            )


class TestSerialization:
    def test_composition_survives_a_reduce_roundtrip_with_shared_refs(self) -> None:
        # copy.deepcopy drives the pickle path; the shared FilteredTableModel and
        # sibling references are preserved because the whole group is one graph.
        group = TableComposition.build(
            TableCompositionSpec(
                columns=("ID", "Status"),
                rows=(("a", "open"), ("b", "closed")),
                filters=(
                    {
                        "type": "combo",
                        "column": 1,
                        "items": ["All", "open", "closed"],
                    },
                ),
            )
        )[0]
        restored = copy.deepcopy(group)
        assert isinstance(restored, GroupElement)
        table = _table(restored)
        combo = _combo(restored)
        # Driving the restored combo still filters the restored table — the model
        # and its table reference came across as one shared object.
        _change(combo, 2)  # "closed"
        assert [row[0] for row in table.rows] == ["b"]
