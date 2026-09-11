"""TreeNodesState — a tree's node data bundled with its reconciled selection."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.tree_node import TreeNode
from punt_lux.protocol.elements.tree_nodes_state import TreeNodesState
from punt_lux.protocol.elements.tree_selection_model import TreeSelectionModel


class TestConstruction:
    def test_defaults_to_empty_nodes_and_display_only_selection(self) -> None:
        state = TreeNodesState()
        assert state.nodes == ()
        assert state.selection.mode == "none"

    def test_computes_live_ids_from_the_given_nodes(self) -> None:
        state = TreeNodesState(
            nodes=(TreeNode(label="a", id="n0"),),
            selection=TreeSelectionModel(mode="multi"),
        )
        selected = state.selected_from_wire(["n0"])
        assert selected.selection.selected_node_ids == frozenset({"n0"})


class TestReplacedNodes:
    def test_decodes_and_installs_the_new_nodes(self) -> None:
        state = TreeNodesState()
        replaced = state.replaced_nodes([{"label": "a", "id": "n0"}])
        assert replaced.nodes == (TreeNode(label="a", id="n0"),)

    def test_reconciles_the_selection_against_the_new_live_ids(self) -> None:
        selection = TreeSelectionModel(mode="multi", selected=frozenset({"n0"}))
        state = TreeNodesState(
            nodes=(TreeNode(label="a", id="n0"),), selection=selection
        )
        replaced = state.replaced_nodes([{"label": "b", "id": "n1"}])
        # n0 no longer exists after the replace -- reconciled drops it.
        assert replaced.selection.selected_node_ids == frozenset()

    def test_raises_on_a_malformed_node(self) -> None:
        state = TreeNodesState()
        with pytest.raises(ValueError, match="must be a mapping"):
            state.replaced_nodes([42])


class TestSelectedFromWire:
    def test_intersects_with_the_live_ids(self) -> None:
        state = TreeNodesState(
            nodes=(TreeNode(label="a", id="n0"),),
            selection=TreeSelectionModel(mode="multi"),
        )
        selected = state.selected_from_wire(["n0", "ghost"])
        assert selected.selection.selected_node_ids == frozenset({"n0"})

    def test_raises_on_a_non_list(self) -> None:
        state = TreeNodesState()
        with pytest.raises(ValueError, match="selected_node_ids"):
            state.selected_from_wire("not-a-list")


class TestAnchored:
    def test_sets_the_anchor_when_it_names_a_selected_node(self) -> None:
        selection = TreeSelectionModel(mode="multi", selected=frozenset({"n0"}))
        state = TreeNodesState(
            nodes=(TreeNode(label="a", id="n0"),), selection=selection
        )
        assert state.anchored("n0").selection.anchor == "n0"


class TestResolvedProps:
    def test_bundles_nodes_and_selection_view_state(self) -> None:
        selection = TreeSelectionModel(mode="single", selected=frozenset({"n0"}))
        state = TreeNodesState(
            nodes=(TreeNode(label="a", id="n0"),), selection=selection
        )
        assert state.resolved_props() == {
            "nodes": [{"label": "a", "id": "n0"}],
            "selection_mode": "single",
            "selected_node_ids": ["n0"],
            "anchor_node_id": "",
        }


class TestReorderedPatch:
    def test_moves_nodes_ahead_of_selection_regardless_of_caller_order(self) -> None:
        patch = {"selected_node_ids": ["n0"], "nodes": [{"label": "a", "id": "n0"}]}
        ordered = list(TreeNodesState.reordered_patch(patch))
        assert ordered.index("nodes") < ordered.index("selected_node_ids")

    def test_moves_selection_ahead_of_anchor(self) -> None:
        patch = {"anchor_node_id": "n0", "selected_node_ids": ["n0"]}
        ordered = list(TreeNodesState.reordered_patch(patch))
        assert ordered.index("selected_node_ids") < ordered.index("anchor_node_id")

    def test_leaves_unrelated_keys_in_their_original_relative_order(self) -> None:
        patch = {"label": "x", "flat": True, "tooltip": "y"}
        ordered = list(TreeNodesState.reordered_patch(patch))
        assert ordered == ["label", "flat", "tooltip"]

    def test_preserves_every_value(self) -> None:
        patch = {"selected_node_ids": ["n0"], "nodes": [{"label": "a", "id": "n0"}]}
        ordered = TreeNodesState.reordered_patch(patch)
        assert ordered == patch
