"""SubtreeInstaller — install a scene-root and its descendants into Hub storage.

Installation is the mirror image of removal (``SubtreeRemover``): it wires a
subtree into the element index, the owner tracker, the root registry, and the
child index in one Composite-Protocol walk, so a Dialog whose Buttons live in
``children`` lands in the index alongside its parent and later clicks resolve.
This class owns that walk so ``HubDisplay`` stays a facade over the collaborators
rather than carrying the install mechanics itself.

A scene-root ABC Element also gets a HubDisplay-owned observer registered:
flipping ``_removed`` on the root fires ``on_root_removed``, which routes the
removal back through ``HubDisplay.apply`` so the index and the Element lifecycle
stay coupled. Child Elements are observed by their parent composite, not here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.composite import Composite
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ElementId

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.root_registry import RootRegistry
    from punt_lux.domain.ids import ConnectionId, SceneId

__all__ = ["SubtreeInstaller"]


@final
class SubtreeInstaller:
    """Install subtrees into the four Hub storage collaborators in one walk."""

    _index: ElementIndex
    _owners: OwnerTracker
    _roots: RootRegistry
    _children: ChildIndex
    _on_root_removed: Callable[[ConnectionId, SceneId, ElementId], None]
    __slots__ = ("_children", "_index", "_on_root_removed", "_owners", "_roots")

    def __new__(
        cls,
        index: ElementIndex,
        owners: OwnerTracker,
        roots: RootRegistry,
        children: ChildIndex,
        on_root_removed: Callable[[ConnectionId, SceneId, ElementId], None],
    ) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._owners = owners
        self._roots = roots
        self._children = children
        self._on_root_removed = on_root_removed
        return self

    def install(
        self,
        scene_id: SceneId,
        element: WireElement,
        *,
        parent_id: ElementId | None,
        owner: ConnectionId,
    ) -> None:
        """Install ``element`` and recurse into composite children.

        Single entry point shared by the root and child branches — the
        display-side ``DomainPump._install_subtree`` follows the same
        Composite-Protocol recursion, so the two stores stay in lockstep.
        Without recursion, a Dialog whose Buttons live in ``children`` would
        land in the index alone; subsequent clicks would route to elements
        ``resolve`` cannot find.
        """
        if parent_id is None:
            key = self._install_scene(scene_id, element, owner=owner)
        else:
            key = self._install_child(scene_id, parent_id, element, owner=owner)
        if isinstance(element, Composite):
            for child in element.children:
                self.install(scene_id, child, parent_id=key, owner=owner)

    def _install_scene(
        self, scene_id: SceneId, element: WireElement, *, owner: ConnectionId
    ) -> ElementId:
        """Install ``element`` as a scene-root; return its assigned store key.

        The key is the element's id for a named element, or a synthesized handle
        for an anonymous one — the index assigns it and every parallel map
        (owners, root registry, observer) keys on the same handle so repeated
        anonymous roots never collapse onto a shared ``""`` slot.
        """
        key = self._index.install_root(scene_id, ElementId(element.id), element)
        self._owners.record(scene_id, key, owner)
        if isinstance(element, AbcElement):
            self._roots.register(scene_id, key, element)
            element.add_observer(self._root_observer_for(scene_id, key))
        return key

    def _install_child(
        self,
        scene_id: SceneId,
        parent_id: ElementId,
        element: WireElement,
        *,
        owner: ConnectionId,
    ) -> ElementId:
        """Install ``element`` under ``parent_id``; return its assigned store key.

        Index-only wiring; the parent-as-observer is the parent composite's
        responsibility, not HubDisplay's. The parent → child edge is recorded so
        cascade removal can drop the descendant from storage even when the parent
        has no observer (wire-only subtrees). An anonymous child keys on a
        synthesized handle, so repeated anonymous children in one parent stay
        distinct throughout the owner and child-edge maps.
        """
        key = self._index.install_child(scene_id, parent_id, element)
        self._owners.record(scene_id, key, owner)
        self._children.record(scene_id, parent_id, key)
        return key

    def _root_observer_for(
        self, scene_id: SceneId, element_id: ElementId
    ) -> Callable[[str], None]:
        """Return the observer callback for a scene-root Element.

        Fires on every property change; on ``"removed"`` it routes the removal
        back through ``HubDisplay.apply`` so the index and the Element lifecycle
        stay coupled.
        """

        def _observe(property_name: str) -> None:
            if property_name != "removed":
                return
            owner = self._owners.get(scene_id, element_id)
            if owner is None:
                return
            self._on_root_removed(owner, scene_id, element_id)

        return _observe
