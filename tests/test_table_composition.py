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
from punt_lux.protocol.compositions import TableComposition, TableCompositionSpec
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


class TestBuilderShape:
    def test_no_chrome_returns_the_bare_grid(self) -> None:
        roots = TableComposition.build(
            TableCompositionSpec(columns=("A",), rows=(("x",),))
        )
        assert len(roots) == 1
        assert isinstance(roots[0], TableElement)
        assert roots[0].selection_mode == "none"

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
