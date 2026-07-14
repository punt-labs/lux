"""HubDisplay — facade over the Hub-side Element/owner/client store.

``HubDisplay`` is the single public surface the rest of the system
talks to for Hub-side scene state. Internally it composes six typed
collaborators, each with one responsibility:

- ``ElementIndex`` (`element_index.py`) — ``(scene_id, element_id) →
  Element`` lookup table.
- ``OwnerTracker`` (`owner_tracker.py`) — every Element's owning
  ``ConnectionId``; ``Display.interact`` gates on this, the disconnect
  path walks it to find each connection's owned roots.
- ``RootRegistry`` (`root_registry.py`) — ``(scene_id, element_id) →
  AbcElement`` for scene-root ABC Elements that participate in the
  property-Observer cascade.
- ``ChildIndex`` (`child_index.py`) — parent → children edges captured
  at install time so cascade removal can drop every descendant from the
  storage layer in one walk.
- ``HubClientRegistry`` (`hub_clients.py`) — set of connections
  currently registered as Hub clients.
- ``FrameRegistry`` (`frame_registry.py`) — ``scene_id → frame_id`` so a
  re-push resends a scene into the frame it was originally shown in;
  forgotten when a teardown leaves the scene with no roots, so it tracks
  scene lifetime like the four collaborators above.

A scene's frame is forgotten on exactly one criterion — the scene has no
roots left — checked uniformly by ``maybe_forget_frame`` after every
teardown: an empty ``replace_scene`` (clear), a ``drop_connection``, and a
direct remove of the last root through ``update``. Keying the forget on the
scene's own state, not on which scenes a connection touched, is what keeps a
shared scene's frame alive while any owner still holds a root in it.

``apply`` dispatches on the typed ``Update`` sum and delegates to the
collaborators. ``drop_connection`` flips ``mark_removed`` on each
ABC-root the connection owned; the Observer cascade prunes the rest of
the tree, ending with the parent composite calling
``apply(RemoveElement(...))``, which clears the index entry and fires
the next layer of observers. Wire-only (non-ABC) roots have no cascade
to drive removal — ``drop_connection`` removes them directly through the
``SubtreeRemover``, which walks the ``ChildIndex`` to drop every descendant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.composite import Composite
from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.element_index import (
    ElementIndex,
    UnknownElementError,
    UnknownSceneError,
)
from punt_lux.domain.hub.frame_registry import FrameRegistry
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.subtree_remover import SubtreeRemover
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    "HubDisplay",
    "HubOwnershipError",
    "UnknownElementError",
    "UnknownSceneError",
    "hub_display",
]


class HubDisplay:
    """Hub-side authoritative store of Elements, owners, and clients.

    Facade over four typed collaborators. State invariants (established
    at ``apply`` time, trusted thereafter):

    - Every Element installed has a known owner ``ConnectionId``.
    - A scene-root ABC Element (``parent_id=None``) has a
      HubDisplay-owned observer registered; flipping ``_removed`` on
      the root triggers a callback into ``apply(RemoveElement(...))``.
    - Child Elements (``parent_id`` set) are observed by their parent
      composite, NOT by HubDisplay — the parent's observer is what
      drives ``apply(RemoveElement(...))`` for the child.

    Tests construct their own ``HubDisplay()``; the module exposes
    ``hub_display`` as the production singleton.
    """

    _index: ElementIndex
    _owners: OwnerTracker
    _roots: RootRegistry
    _children: ChildIndex
    _clients: HubClientRegistry
    _frames: FrameRegistry
    _seam: WriteSeam
    _remover: SubtreeRemover

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._index = ElementIndex()
        self._owners = OwnerTracker()
        self._roots = RootRegistry()
        self._children = ChildIndex()
        self._clients = HubClientRegistry()
        self._frames = FrameRegistry()
        self._seam = WriteSeam(self._index, self._children)
        self._remover = SubtreeRemover(
            self._index, self._owners, self._roots, self._children
        )
        return self

    @property
    def write_seam(self) -> WriteSeam:
        """Return the field-mutation seam the authoritative write path uses."""
        return self._seam

    # -- clients registry --------------------------------------------------

    def register_client(self, connection_id: ConnectionId) -> None:
        """Mark a connection as a known client. Idempotent."""
        self._clients.register(connection_id)

    def is_client(self, connection_id: ConnectionId) -> bool:
        """Return True if the connection is currently registered."""
        return self._clients.is_registered(connection_id)

    # -- index access ------------------------------------------------------

    def scene_roots(self, scene_id: SceneId) -> list[WireElement]:
        """Return non-removed root elements for a scene."""
        return self._index.scene_roots(scene_id)

    # -- frame association -------------------------------------------------

    def record_frame(self, scene_id: SceneId, frame_id: str) -> None:
        """Remember the frame a scene was shown in, for a later re-push."""
        self._frames.record(scene_id, frame_id)

    def frame_id_for(self, scene_id: SceneId) -> str:
        """Return the frame a scene was shown in, or its own id when unrecorded."""
        return self._frames.frame_for(scene_id)

    def maybe_forget_frame(self, scene_id: SceneId) -> None:
        """Forget the scene's frame association iff no root remains in it.

        The single teardown criterion, checked uniformly after every path
        that can empty a scene — an empty ``replace_scene`` (clear), a
        ``drop_connection``, and a direct remove of the last root through
        ``update``. Keying on the scene's own roots, not on which scenes a
        connection touched, is what leaves a shared scene's frame intact while
        any owner still holds a root in it. A later re-show re-records; until
        then ``frame_id_for`` reverts to the scene's own id.
        """
        if not self.scene_roots(scene_id):
            self._frames.forget(scene_id)

    def resolve(self, scene_id: SceneId, element_id: ElementId) -> WireElement:
        """Return the indexed Element or raise ``UnknownElementError``."""
        return self._index.lookup(scene_id, element_id)

    def owner_of(self, scene_id: SceneId, element_id: ElementId) -> ConnectionId:
        """Return the connection that installed the Element.

        Raises ``UnknownElementError`` if the element is not indexed —
        ownership of an absent element is meaningless.
        """
        owner = self._owners.get(scene_id, element_id)
        if owner is None:
            raise UnknownElementError(scene_id=scene_id, element_id=element_id)
        return owner

    def elements_owned_by(
        self,
        connection_id: ConnectionId,
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        return self._owners.keys_for(connection_id)

    @trace
    def replace_scene(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        roots: Sequence[WireElement],
    ) -> None:
        """Replace ``scene_id`` for ``connection_id`` with ``roots``.

        The Hub stays authoritative: a re-show first removes every root
        this connection previously owned in the scene, then installs the
        new roots through the normal ``apply(AddElement(...))`` path so
        ownership, root observers, and child indexes are rebuilt in one
        place.
        """
        self.register_client(connection_id)
        for root_id in self._owned_roots_in_scene(connection_id, scene_id):
            self.apply(
                connection_id,
                RemoveElement(scene_id=scene_id, element_id=root_id),
            )
        for root in roots:
            self.apply(
                connection_id,
                AddElement(scene_id=scene_id, element=root, parent_id=None),
            )
        self.maybe_forget_frame(scene_id)

    # -- apply -------------------------------------------------------------

    def apply(
        self,
        connection_id: ConnectionId,
        update: AddElement | SetProperty | RemoveElement,
    ) -> None:
        """Commit a state change to the index. Owner is the caller.

        ``AddElement`` installs the root and then recurses into composite
        children using the Composite Protocol — the same structural-typing
        gate the display-side pump uses. Click resolution downstream is
        keyed by ``(scene, element_id)``; a child Button buried in a
        Dialog is reachable only if its row sits in the index.

        ``SetProperty`` and ``RemoveElement`` are mutations against an
        already-installed element and require the caller to own that
        element. The check mirrors ``Display.apply``'s ownership
        enforcement so a misbehaving client cannot mutate or evict
        another client's state from the Hub mirror.
        """
        match update:
            case AddElement(scene_id=sid, parent_id=pid, element=elem):
                self._install_subtree(sid, elem, parent_id=pid, owner=connection_id)
            case SetProperty(scene_id=sid, element_id=eid, field=field, value=value):
                self._owners.require_ownership(sid, eid, connection_id)
                self._seam.set_property(sid, eid, field, value)
            case RemoveElement(scene_id=sid, element_id=eid):
                self._owners.require_ownership(sid, eid, connection_id)
                self._remover.remove_subtree(sid, eid)

    def _owned_roots_in_scene(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
    ) -> tuple[ElementId, ...]:
        """Return the scene-root ids this connection currently owns."""
        return tuple(
            element_id
            for owned_scene, element_id in self._owners.keys_for(connection_id)
            if owned_scene == scene_id
            and self._children.is_root(owned_scene, element_id)
        )

    # -- cleanup trigger ---------------------------------------------------

    def drop_connection(self, connection_id: ConnectionId) -> None:
        """Forget the client and ``mark_removed`` every root it owned.

        Does NOT walk the subtree itself — that bypasses the Observer
        cascade and leaves parent composites' children tuples stale.
        Only ABC Elements participate in the cascade; wire-dataclass
        roots have no observer registry and are dropped by direct index
        cleanup in the ``SubtreeRemover``.

        After the roots are torn down, each scene the connection touched is
        offered to ``maybe_forget_frame``: a scene another connection still
        holds a root in keeps its frame, a scene now empty gives it up.
        """
        self._clients.discard(connection_id)
        owned = self._owners.keys_for(connection_id)
        for scene_id, element_id in owned:
            if self._children.is_root(scene_id, element_id):
                self._remover.drop_root(scene_id, element_id, connection_id)
        for scene_id in {scene for scene, _ in owned}:
            self.maybe_forget_frame(scene_id)

    # -- private helpers ---------------------------------------------------

    def _install_subtree(
        self,
        scene_id: SceneId,
        element: WireElement,
        *,
        parent_id: ElementId | None,
        owner: ConnectionId,
    ) -> None:
        """Install ``element`` and recurse into composite children.

        Single entry point shared by both the root and child branches —
        the display-side ``DomainPump._install_subtree`` follows the
        same Composite-Protocol recursion shape so the two stores stay
        in lockstep. Without recursion, a Dialog whose Buttons live in
        ``children`` would land in the index alone; subsequent clicks
        would route to elements ``resolve`` cannot find.
        """
        if parent_id is None:
            key = self._install_scene(scene_id, element, owner=owner)
        else:
            key = self._install_child(scene_id, parent_id, element, owner=owner)
        if isinstance(element, Composite):
            for child in element.children:
                self._install_subtree(scene_id, child, parent_id=key, owner=owner)

    def _install_scene(
        self, scene_id: SceneId, element: WireElement, *, owner: ConnectionId
    ) -> ElementId:
        """Install ``element`` as a scene-root; return its assigned store key.

        The key is the element's id for a named element, or a synthesized
        handle for an anonymous one — the index assigns it and every parallel
        map (owners, root registry, observer) keys on the same handle so
        repeated anonymous roots never collapse onto a shared ``""`` slot.
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
        responsibility, not HubDisplay's. The parent → child edge is recorded
        so cascade removal can drop the descendant from storage even when the
        parent has no observer (wire-only subtrees). An anonymous child keys on
        a synthesized handle, so repeated anonymous children in one parent stay
        distinct throughout the owner and child-edge maps.
        """
        key = self._index.install_child(scene_id, parent_id, element)
        self._owners.record(scene_id, key, owner)
        self._children.record(scene_id, parent_id, key)
        return key

    def _remove_subtree(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Clear the element and every descendant from storage.

        Walks the ``ChildIndex`` to enumerate descendants in install
        order, then drops each in turn. For ABC subtrees the Observer
        cascade has already pruned the parent composite's children
        tuple; for wire-only subtrees no cascade exists, so this walk
        is the sole removal path. Either way, storage cleanup runs
        here so future ``resolve`` calls fail loud.
        """
        for descendant_id in self._children.descendants(scene_id, element_id):
            self._drop_storage(scene_id, descendant_id)
        self._drop_storage(scene_id, element_id)

    def _drop_storage(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop one element from every storage collaborator. Idempotent."""
        self._index.discard(scene_id, element_id)
        self._owners.discard(scene_id, element_id)
        self._roots.discard(scene_id, element_id)
        self._children.discard(scene_id, element_id)

    def _root_observer_for(
        self, scene_id: SceneId, element_id: ElementId
    ) -> Callable[[str], None]:
        """Return the observer callback for a scene-root Element.

        Fires on every property change; on ``"removed"`` it routes the
        removal back through ``apply(RemoveElement(...))`` so the index
        and the Element's lifecycle stay coupled.
        """

        def _observe(property_name: str) -> None:
            if property_name != "removed":
                return
            owner = self._owners.get(scene_id, element_id)
            if owner is None:
                return
            self.apply(owner, RemoveElement(scene_id=scene_id, element_id=element_id))

        return _observe


hub_display = HubDisplay()
