"""Tree-walk reachability and physical-removal tests for SceneTreeWalk.

Two invariants guard the walk:

- **Container coverage.** ``collect_ids`` recurses every ``HasChildElements``
  container via the Protocol, but ``find`` descends legacy containers through
  an explicit ladder. If a legacy container kind is missing from that ladder,
  ``find`` cannot reach a child ``collect_ids`` reports — a patch on that child
  becomes a silent no-op. The structural test parametrizes over EVERY legacy
  container kind so a future kind cannot reintroduce the gap.

- **Physical removal.** A remove routed to an ABC container drops the child from
  the parent's tuple, so the render walk over ``_children()`` no longer paints
  it — never a lingering node flagged removed but still rendered.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.protocol import (
    Element,
    GroupElement,
    LegacyCollapsingHeaderElement,
    LegacyGroupElement,
    LegacyTabBarElement,
    ModalElement,
    TextElement,
    WindowElement,
)
from punt_lux.scene.element_walk import AbcNode, ListSlot, SceneTreeWalk


def _legacy_containers_with_child(child: TextElement) -> list[tuple[str, Element]]:
    """Return one instance of every legacy HasChildElements kind wrapping ``child``.

    ``TreeElement`` is excluded on purpose — its nodes are plain mappings, so
    ``child_elements()`` returns ``()`` and it never carries element children.
    """
    return [
        ("group", LegacyGroupElement(id="p", children=[child])),
        (
            "tab_bar",
            LegacyTabBarElement(id="p", tabs=[{"label": "T", "children": [child]}]),
        ),
        ("window", WindowElement(id="p", children=[child], title="W")),
        ("collapsing_header", LegacyCollapsingHeaderElement(id="p", children=[child])),
        ("modal", ModalElement(id="p", children=[child])),
    ]


_CHILD = TextElement(id="c1", content="x")


@pytest.mark.parametrize(
    "container",
    [c for _, c in _legacy_containers_with_child(_CHILD)],
    ids=[name for name, _ in _legacy_containers_with_child(_CHILD)],
)
def test_find_reaches_child_in_every_legacy_container(container: Element) -> None:
    """``find`` reaches a nested child in EVERY legacy container kind.

    A missing branch in ``_legacy_child_lists`` makes ``find`` return None for a
    child that ``collect_ids`` reports — the exact walk-coverage gap that has
    recurred. Parametrizing over the whole container set turns any future
    omission into a hard failure here.
    """
    walk = SceneTreeWalk()

    # ``collect_ids`` reports the child (Protocol recursion) ...
    assert "c1" in walk.collect_ids(container)
    # ... so ``find`` must be able to reach it too.
    location = walk.find([container], "c1")
    assert location is not None
    assert location.element.id == "c1"
    assert isinstance(location, ListSlot)


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
