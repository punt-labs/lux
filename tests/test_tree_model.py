"""TreeModel -- a tree's identity, look and content, replaced whole by each patch."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.tree_model import TreeModel
from punt_lux.protocol.elements.tree_nodes_state import TreeNodesState
from punt_lux.protocol.elements.tree_selection_model import TreeSelectionModel


def _model() -> TreeModel:
    return TreeModel(id="t", content=TreeNodesState())


class TestPatchedFields:
    def test_a_label_replaces_the_label_and_leaves_the_rest(self) -> None:
        patched = _model().labelled("files")

        assert (patched.id, patched.label, patched.flat) == ("t", "files", False)

    def test_flatness_and_tooltip_are_replaced(self) -> None:
        patched = _model().flattened(True).tipped("hint")

        assert (patched.flat, patched.tooltip) == (True, "hint")

    def test_a_null_tooltip_clears_it(self) -> None:
        assert _model().tipped("hint").tipped(None).tooltip is None

    def test_a_patch_is_never_applied_in_place(self) -> None:
        model = _model()
        model.labelled("files")

        assert model.label == ""

    @pytest.mark.parametrize("name", ["labelled", "flattened"])
    def test_a_value_of_the_wrong_type_is_refused(self, name: str) -> None:
        with pytest.raises((TypeError, ValueError)):
            getattr(_model(), name)(object())


class TestContent:
    def test_the_selection_is_the_contents(self) -> None:
        selection = TreeSelectionModel(mode="multi")
        model = TreeModel(id="t", content=TreeNodesState(selection=selection))

        assert model.selection is selection

    def test_replacing_the_content_keeps_the_look(self) -> None:
        model = _model().labelled("files")

        assert model.with_content(TreeNodesState()).label == "files"


def test_resolved_props_report_the_look_and_the_content() -> None:
    props = _model().labelled("files").resolved_props()

    assert props["label"] == "files"
    assert "selection_mode" in props
