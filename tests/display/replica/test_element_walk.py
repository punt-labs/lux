"""Tree-walk reachability and physical-removal tests for SceneTreeWalk.

Two invariants guard the walk:

- **Container coverage.** ``collect_ids`` recurses every ``HasChildElements``
  container via the Protocol, and ``find`` descends the same subtree. A child
  ``collect_ids`` reports must be reachable by ``find`` too, or a patch on that
  child becomes a silent no-op.

- **Physical removal.** A remove routed to an ABC container drops the child from
  the parent's tuple, so the render walk over ``_children()`` no longer paints
  it — never a lingering node flagged removed but still rendered.
"""

from __future__ import annotations

from punt_lux.display.replica.element_walk import AbcNode, SceneTreeWalk
from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.protocol import GroupElement, TextElement


def test_find_reaches_nested_child_in_abc_container() -> None:
    """A child ``collect_ids`` reports in an ABC container is reachable by ``find``.

    ``collect_ids`` recurses containers via the ``HasChildElements`` Protocol and
    ``find`` descends the same subtree; the two must agree or a patch on a nested
    child becomes a silent no-op.
    """
    child = TextElement(id="c1", content="x")
    container = GroupElement(id="p", children=(child,))
    walk = SceneTreeWalk()

    # ``collect_ids`` reports the child (Protocol recursion) ...
    assert "c1" in walk.collect_ids(container)
    # ... so ``find`` must reach it too — as a nested AbcNode.
    location = walk.find([container], "c1")
    assert location is not None
    assert location.element.id == "c1"
    assert isinstance(location, AbcNode)


class TestAbcRemovalIsPhysical:
    """A remove routed to an ABC container drops the child from the render."""

    def test_find_locates_abc_group_child_with_parent(self) -> None:
        """A child nested in an ABC group is an ``AbcNode`` carrying its parent."""
        group = GroupElement(
            id="g1",
            layout="rows",
            children=(TextElement(id="c1", content="x"),),
        )
        location = SceneTreeWalk().find([group], "c1")
        assert isinstance(location, AbcNode)
        assert location.element.id == "c1"

    def test_detach_removes_child_from_parent_children(self) -> None:
        """``detach`` drops the child from what the parent renders."""
        gone = TextElement(id="c1", content="x")
        kept = TextElement(id="c2", content="y")
        group = GroupElement(id="g1", layout="rows", children=(gone, kept))

        location = SceneTreeWalk().find([group], "c1")
        assert isinstance(location, AbcNode)
        detached = location.detach()

        assert detached.id == "c1"
        # The render walks ``children`` (== ``_children()``); the removed child
        # must be ABSENT, not merely flagged.
        assert [c.id for c in group.children] == ["c2"]

    def test_remove_absent_child_is_a_noop(self) -> None:
        """Removing a child a node does not hold leaves its children untouched.

        ``remove_child`` matches by identity, so a mis-routed remove (or a
        leaf, whose tuple is always empty) changes nothing — the removal is
        idempotent set-semantics, never a partial mutation.
        """
        kept = TextElement(id="c2", content="y")
        stranger = TextElement(id="x", content="z")
        group = GroupElement(id="g1", layout="rows", children=(kept,))

        group.remove_child(stranger)

        assert [c.id for c in group.children] == ["c2"]

    def test_leaf_has_no_children_to_remove(self) -> None:
        """A leaf carries an empty child tuple; removing from it is a no-op."""
        leaf = TextElement(id="c1", content="x")
        assert isinstance(leaf, ABCElement)
        assert leaf.child_elements() == ()
        leaf.remove_child(leaf)  # no children — nothing changes, no raise
        assert leaf.child_elements() == ()
