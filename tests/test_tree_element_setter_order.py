"""A tree's patch runs its nodes first, then its selection, whatever the key order."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.protocol.elements import TreeElement
from punt_lux.protocol.elements.tree_node import TreeNode

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest


def _tree() -> TreeElement:
    return TreeElement(id="t", selection_mode="multi")


class TestTheOrderTheSettersRunIn:
    @staticmethod
    def _run(monkeypatch: pytest.MonkeyPatch, patch: Mapping[str, object]) -> list[str]:
        ran: list[str] = []
        for name in ("nodes", "selected_node_ids", "anchor_node_id", "label"):
            real = getattr(TreeElement, f"_set_{name}")

            def spy(
                this: TreeElement,
                value: object,
                name: str = name,
                real: object = real,
            ) -> None:
                ran.append(name)
                real(this, value)  # type: ignore[operator]  # the setter being spied

            monkeypatch.setattr(TreeElement, f"_set_{name}", spy)
        _tree().apply_patch(patch)
        return ran

    def test_nodes_run_ahead_of_the_selection_whatever_the_callers_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch = {"selected_node_ids": ["n0"], "nodes": [{"label": "a", "id": "n0"}]}

        ran = self._run(monkeypatch, patch)

        assert ran.index("nodes") < ran.index("selected_node_ids")

    def test_the_selection_runs_ahead_of_the_anchor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch = {"anchor_node_id": "n0", "selected_node_ids": ["n0"], "nodes": []}

        ran = self._run(monkeypatch, patch)

        assert ran == ["nodes", "selected_node_ids", "anchor_node_id"]

    def test_the_other_keys_follow_in_the_callers_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch = {"label": "x", "nodes": []}

        assert self._run(monkeypatch, patch) == ["nodes", "label"]

    def test_a_selection_of_ids_only_the_new_tree_has_is_kept(self) -> None:
        tree = _tree()

        tree.apply_patch(
            {"selected_node_ids": ["n0"], "nodes": [{"label": "a", "id": "n0"}]}
        )

        assert tree.nodes == (TreeNode(label="a", id="n0"),)
        assert tree.selected_node_ids == frozenset({"n0"})
