"""Unit tests for ``tools/oo_coupling.py``'s cycle-member detection.

``CouplingScorer._find_cycle_members`` decides the ``circular_imports``
metric for every module in the ratchet, so a correctness bug here silently
lets a real circular import through the gate. These tests exercise it
directly against small hand-built import graphs, without touching the
filesystem.
"""

from __future__ import annotations

from tools.oo_coupling import CouplingScorer


class TestFindCycleMembers:
    """``_find_cycle_members`` must report every node in any cycle."""

    def test_three_node_cycle_reports_all_members(self) -> None:
        """A->B, A->C, B->A, C->B is one cycle; every node is a member.

        Regression guard for the DFS-path bug qodo found on lux PR #466:
        the old algorithm only recorded cycle membership on a back-edge
        into a still-on-stack (GRAY) node. A sorted DFS visits B before C,
        finds the A->B->A back-edge, and marks only {A, B} -- C is reached
        solely through the already-finished (BLACK) B node and is silently
        dropped, even though C->B->A->C is a real cycle.
        """
        graph = {"A": {"B", "C"}, "B": {"A"}, "C": {"B"}}

        assert CouplingScorer._find_cycle_members(graph) == {"A", "B", "C"}

    def test_simple_two_node_cycle(self) -> None:
        """A minimal mutual-import cycle is reported in full."""
        graph = {"X": {"Y"}, "Y": {"X"}, "Z": set()}

        assert CouplingScorer._find_cycle_members(graph) == {"X", "Y"}

    def test_acyclic_graph_reports_no_members(self) -> None:
        """A linear import chain has no cycle members."""
        graph = {"P": {"Q"}, "Q": {"R"}, "R": set()}

        assert CouplingScorer._find_cycle_members(graph) == set()

    def test_self_loop_is_a_cycle_of_one(self) -> None:
        """A module that imports itself is its own cycle."""
        graph = {"S": {"S"}}

        assert CouplingScorer._find_cycle_members(graph) == {"S"}

    def test_disjoint_cycles_are_each_fully_reported(self) -> None:
        """Two separate cycles in one graph each report all their members."""
        graph = {
            "A": {"B"},
            "B": {"A"},
            "C": {"D"},
            "D": {"C"},
            "E": set(),
        }

        assert CouplingScorer._find_cycle_members(graph) == {"A", "B", "C", "D"}

    def test_result_is_deterministic_across_dict_orderings(self) -> None:
        """Membership does not depend on the graph's key insertion order.

        Str-keyed set iteration order depends on ``PYTHONHASHSEED``, which
        is randomized per process -- the fix must derive membership from
        Tarjan's SCC structure, not incidental traversal order, so the same
        source graph produces the same answer regardless of dict layout.
        """
        forward = {"A": {"B", "C"}, "B": {"A"}, "C": {"B"}}
        reordered = {"C": {"B"}, "B": {"A"}, "A": {"C", "B"}}

        assert CouplingScorer._find_cycle_members(
            forward
        ) == CouplingScorer._find_cycle_members(reordered)
