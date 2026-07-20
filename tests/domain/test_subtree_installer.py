"""SubtreeInstaller wires a scene-root and its descendants into every store.

The installer is the mirror of ``SubtreeRemover``: one Composite-Protocol walk
must land the root and every child across index, owners, and child edges, and a
scene-root ABC element must get an observer that routes its self-removal back
through the ``on_root_removed`` callback ``HubDisplay`` supplies.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.element_index import ElementIndex
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.subtree_installer import SubtreeInstaller
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.protocol.elements import ButtonElement, GroupElement, TextElement

_SCENE = SceneId("installer-scene")
_OWNER = ConnectionId("owner-conn")


class _Store:
    """The four storage collaborators plus an installer wired over them.

    Mirrors ``HubDisplay``'s composition so the installer runs against the real
    collaborators, not stubs. ``removed`` records every callback invocation.
    """

    index: ElementIndex
    owners: OwnerTracker
    roots: RootRegistry
    children: ChildIndex
    installer: SubtreeInstaller
    removed: list[tuple[ConnectionId, SceneId, ElementId]]
    __slots__ = ("children", "index", "installer", "owners", "removed", "roots")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.index = ElementIndex()
        self.owners = OwnerTracker()
        self.roots = RootRegistry()
        self.children = ChildIndex()
        self.removed = []
        self.installer = SubtreeInstaller(
            self.index, self.owners, self.roots, self.children, self._record_removed
        )
        return self

    def _record_removed(
        self, owner: ConnectionId, scene_id: SceneId, element_id: ElementId
    ) -> None:
        self.removed.append((owner, scene_id, element_id))


def test_install_root_lands_in_index_and_owners() -> None:
    store = _Store()
    root = TextElement(id="root", content="hi")

    store.installer.install(_SCENE, root, parent_id=None, owner=_OWNER)

    assert store.index.contains(_SCENE, ElementId("root"))
    assert store.owners.get(_SCENE, ElementId("root")) == _OWNER
    assert store.children.is_root(_SCENE, ElementId("root"))


def test_install_composite_recurses_into_children() -> None:
    store = _Store()
    group = GroupElement(id="grp", children=[TextElement(id="c1", content="a")])

    store.installer.install(_SCENE, group, parent_id=None, owner=_OWNER)

    assert store.index.contains(_SCENE, ElementId("grp"))
    assert store.index.contains(_SCENE, ElementId("c1"))
    # The child lands under the parent edge, never hoisted to a root.
    assert not store.children.is_root(_SCENE, ElementId("c1"))


def test_abc_root_removal_routes_through_the_callback() -> None:
    store = _Store()
    button = ButtonElement(id="go", label="Go")

    store.installer.install(_SCENE, button, parent_id=None, owner=_OWNER)
    button.mark_removed()

    assert store.removed == [(_OWNER, _SCENE, ElementId("go"))]
