"""SubtreeRemover drops a scene-root and its descendants from every store.

The remover is the teardown walk ``HubDisplay`` delegates to. Removal must clear
all four storage collaborators — index, owners, roots, children — for a subtree
in one pass, or a later ``lookup`` finds an orphaned descendant. ``drop_root``
adds the disconnect-path fork: an ABC root is flipped ``mark_removed`` so its
observer cascade drives removal; a wire-only root, having no observer, is torn
down directly through the walk.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.element_index import ElementIndex
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.subtree_remover import SubtreeRemover
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.protocol.elements.text import TextElement

_SCENE = SceneId("remover-scene")
_OWNER = ConnectionId("owner-conn")
_ROOT = ElementId("root")
_CHILD = ElementId("child")


class _Store:
    """The four storage collaborators plus a remover wired over them.

    Mirrors ``HubDisplay``'s composition so the remover is exercised against
    the real collaborators, not stubs.
    """

    index: ElementIndex
    owners: OwnerTracker
    roots: RootRegistry
    children: ChildIndex
    remover: SubtreeRemover
    __slots__ = ("children", "index", "owners", "remover", "roots")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.index = ElementIndex()
        self.owners = OwnerTracker()
        self.roots = RootRegistry()
        self.children = ChildIndex()
        self.remover = SubtreeRemover(
            self.index, self.owners, self.roots, self.children
        )
        return self

    def install_wire_root_with_child(self) -> None:
        """Install a wire root with one wire child recorded across every map."""
        root = TextElement(id=str(_ROOT), content="root")
        child = TextElement(id=str(_CHILD), content="child")
        self.index.install_root(_SCENE, _ROOT, root)
        self.owners.record(_SCENE, _ROOT, _OWNER)
        self.index.install_child(_SCENE, _ROOT, child)
        self.owners.record(_SCENE, _CHILD, _OWNER)
        self.children.record(_SCENE, _ROOT, _CHILD)


def test_remove_subtree_clears_root_and_descendant_from_every_store() -> None:
    """One walk drops the root and its child from index, owners, and children."""
    store = _Store()
    store.install_wire_root_with_child()

    store.remover.remove_subtree(_SCENE, _ROOT)

    assert not store.index.contains(_SCENE, _ROOT)
    assert not store.index.contains(_SCENE, _CHILD)
    assert store.owners.get(_SCENE, _ROOT) is None
    assert store.owners.get(_SCENE, _CHILD) is None
    # The child edge is gone, so the child would now read as a root.
    assert store.children.is_root(_SCENE, _CHILD)


def test_drop_root_of_wire_root_tears_down_through_the_walk() -> None:
    """A root absent from the RootRegistry is a wire root — dropped directly."""
    store = _Store()
    store.install_wire_root_with_child()

    store.remover.drop_root(_SCENE, _ROOT, _OWNER)

    assert not store.index.contains(_SCENE, _ROOT)
    assert not store.index.contains(_SCENE, _CHILD)


def test_drop_root_of_abc_root_marks_removed_and_lets_the_cascade_run() -> None:
    """An ABC root is flipped ``mark_removed``; its observer drives the walk.

    This mirrors ``HubDisplay``, which registers an observer that routes the
    root's ``removed`` signal back through the remover. ``drop_root`` only
    triggers the flag; the cascade does the storage teardown.
    """
    store = _Store()
    root = TextElement(id=str(_ROOT), content="root")
    store.index.install_root(_SCENE, _ROOT, root)
    store.owners.record(_SCENE, _ROOT, _OWNER)
    store.roots.register(_SCENE, _ROOT, root)
    root.add_observer(
        lambda prop: (
            store.remover.remove_subtree(_SCENE, _ROOT) if prop == "removed" else None
        )
    )

    store.remover.drop_root(_SCENE, _ROOT, _OWNER)

    assert root.removed
    assert not store.index.contains(_SCENE, _ROOT)
