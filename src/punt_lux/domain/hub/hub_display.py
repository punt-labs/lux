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
- ``ScenePresentationRegistry`` (`scene_presentation.py`) — ``scene_id →
  ScenePresentation`` so a resend repaints a scene into the frame, with the
  title, size, and layout it was originally shown with; forgotten when a
  teardown leaves the scene with no roots, so it tracks scene lifetime like
  the four collaborators above.

A scene's frame is forgotten on exactly one criterion — the scene has no
roots left — checked uniformly by ``maybe_forget_frame`` after every
teardown: an empty ``replace_scene`` (clear), a ``drop_connection``, and a
direct remove of the last root through ``update``. Keying the forget on the
scene's own state, not on which scenes a connection touched, is what keeps a
shared scene's frame alive while any owner still holds a root in it.

``apply`` dispatches on the typed ``Update`` sum and delegates the install and
teardown walks to two mirror collaborators — ``SubtreeInstaller`` wires a
subtree into every storage map, ``SubtreeRemover`` tears one out.
``drop_connection`` flips ``mark_removed`` on each ABC-root the connection
owned; the Observer cascade prunes the rest of the tree, ending with the parent
composite calling ``apply(RemoveElement(...))``, which clears the index entry
and fires the next layer of observers. Wire-only (non-ABC) roots have no cascade
to drive removal — ``drop_connection`` removes them directly through the
``SubtreeRemover``, which walks the ``ChildIndex`` to drop every descendant.

Every write runs under ``StoreLock`` so the replicator's snapshot never reads a
half-applied scene; the replicator takes the same lock, in read mode, only to
copy a scene out before it resends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.element_index import (
    ElementIndex,
    UnknownElementError,
    UnknownSceneError,
)
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.scene_presentation import (
    ScenePresentation,
    ScenePresentationRegistry,
)
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.hub.subtree_installer import SubtreeInstaller
from punt_lux.domain.hub.subtree_remover import SubtreeRemover
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractContextManager

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
    _frames: ScenePresentationRegistry
    _seam: WriteSeam
    _remover: SubtreeRemover
    _installer: SubtreeInstaller
    _lock: StoreLock

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._index = ElementIndex()
        self._owners = OwnerTracker()
        self._roots = RootRegistry()
        self._children = ChildIndex()
        self._clients = HubClientRegistry()
        self._frames = ScenePresentationRegistry()
        self._seam = WriteSeam(self._index, self._children)
        self._remover = SubtreeRemover(
            self._index, self._owners, self._roots, self._children
        )
        self._installer = SubtreeInstaller(
            self._index,
            self._owners,
            self._roots,
            self._children,
            self._remove_root,
        )
        self._lock = StoreLock()
        return self

    @property
    def write_seam(self) -> WriteSeam:
        """Return the field-mutation seam the authoritative write path uses."""
        return self._seam

    def read_lock(self) -> AbstractContextManager[bool]:
        """Hold the store lock while the replicator copies a scene out to resend.

        Released before the send, so the store lock and the client send lock are
        never held together.
        """
        return self._lock.read()

    def write_lock(self) -> AbstractContextManager[bool]:
        """Hold the store lock across an external mutation batch.

        ``HubSceneWriter`` takes this so its whole parse-guard-commit-remove batch
        commits under one lock and the replicator's snapshot never lands mid-batch;
        reentrant, so nested ``apply`` / ``replace_scene`` re-enter it freely.
        """
        return self._lock.write()

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

    def scene_ids(self) -> tuple[SceneId, ...]:
        """Return every scene that still holds at least one non-removed root.

        The replicator marks each one dirty after a display respawn so the
        fresh, empty display is repainted from the store's current state; a
        since-emptied scene is omitted so nothing repaints a blank.
        """
        return tuple(s for s in self._index.scenes() if self.scene_roots(s))

    # -- presentation ------------------------------------------------------

    def record_presentation(
        self, scene_id: SceneId, presentation: ScenePresentation
    ) -> None:
        """Remember how a scene was shown, for a later whole-scene resend."""
        with self._lock.write():
            self._frames.record(scene_id, presentation)

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return how a scene was shown, or a self-framed default."""
        return self._frames.presentation_for(scene_id)

    def maybe_forget_frame(self, scene_id: SceneId) -> None:
        """Forget the scene's presentation iff no root remains in it.

        The single teardown criterion, checked uniformly after every path
        that can empty a scene — an empty ``replace_scene`` (clear), a
        ``drop_connection``, and a direct remove of the last root through
        ``update``. Keying on the scene's own roots, not on which scenes a
        connection touched, is what leaves a shared scene's frame intact while
        any owner still holds a root in it. A later re-show re-records; until
        then ``presentation_for`` reverts to a frame named for the scene.
        """
        with self._lock.write():
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
        with self._lock.write():
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
        with self._lock.write():
            match update:
                case AddElement(scene_id=sid, parent_id=pid, element=elem):
                    self._installer.install(
                        sid, elem, parent_id=pid, owner=connection_id
                    )
                case SetProperty(
                    scene_id=sid, element_id=eid, field=field, value=value
                ):
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
        """Forget the client, tear down every root it owned, and forget emptied
        frames.

        Does NOT walk the subtree itself — that bypasses the Observer cascade and
        leaves parent composites' children stale. ABC roots drop via the cascade;
        wire-dataclass roots have no observer and drop through the SubtreeRemover.
        A scene another connection still holds a root in keeps its frame.
        """
        self._clients.discard(connection_id)
        owned = self._owners.keys_for(connection_id)
        self._drop_owned_roots(connection_id, owned)
        self._forget_frames_for({scene for scene, _ in owned})

    def _drop_owned_roots(
        self,
        connection_id: ConnectionId,
        owned: tuple[tuple[SceneId, ElementId], ...],
    ) -> None:
        """Tear down each scene-root the connection owned, leaving children to
        the Observer cascade."""
        for scene_id, element_id in owned:
            if self._children.is_root(scene_id, element_id):
                self._remover.drop_root(scene_id, element_id, connection_id)

    def _forget_frames_for(self, scene_ids: set[SceneId]) -> None:
        """Offer each touched scene to ``maybe_forget_frame`` after a teardown."""
        for scene_id in scene_ids:
            self.maybe_forget_frame(scene_id)

    # -- private helpers ---------------------------------------------------

    def _remove_root(
        self, owner: ConnectionId, scene_id: SceneId, element_id: ElementId
    ) -> None:
        """Route an ABC root's self-removal back through the authoritative path.

        The installer registers this as the scene-root observer callback; when a
        root flips ``_removed`` it lands here, and the removal runs through
        ``apply`` so ownership enforcement and the storage teardown are shared
        with every other remove.
        """
        self.apply(owner, RemoveElement(scene_id=scene_id, element_id=element_id))


hub_display = HubDisplay()
