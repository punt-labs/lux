"""HubDisplay — facade over the Hub-side Element/owner/client store.

``HubDisplay`` is the single public surface the rest of the system talks to for
Hub-side scene state. Internally it composes typed collaborators, each with one
responsibility:

- ``ElementIndex`` — ``(scene_id, element_id) → Element`` lookup.
- ``OwnerTracker`` — every Element's owning ``ConnectionId``.
- ``RootRegistry`` — scene-root ABC Elements in the property-Observer cascade.
- ``ChildIndex`` — parent → children edges for one-walk descendant removal.
- ``HubClientRegistry`` — connections registered as Hub clients.
- ``ScenePresentationRegistry`` — how each live scene is framed for a resend.
- ``SubtreeInstaller`` / ``SubtreeRemover`` — the mirror install and teardown
  walks ``apply`` delegates to.

A scene's presentation is kept until the scene is blanked away or re-shown, so an
emptied scene can still be blanked into the frame it was shown in; once the
replicator delivers that blank it reclaims the presentation. ``drop_connection``
tears down each root a departing connection owned — ABC roots via the Observer
cascade, wire-only roots directly through the ``SubtreeRemover`` — and returns the
scenes it touched so the caller can repaint them.

Every write runs under ``StoreLock`` so a snapshot never reads a half-applied
scene. Every read takes the lock in read mode too — the replicator's crossing
reads through ``scene_snapshot`` and ``live_scene_ids``, and the facade's own
``scene_roots`` and ``presentation_for`` — so the lock discipline is the store's
own behavior and never escapes to the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.connection_dropper import ConnectionDropper
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
from punt_lux.domain.hub.scene_snapshot import SceneReader
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.hub.subtree_installer import SubtreeInstaller
from punt_lux.domain.hub.subtree_remover import SubtreeRemover
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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
    _reader: SceneReader
    _dropper: ConnectionDropper

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
        self._reader = SceneReader(self._index, self._frames, self._lock)
        self._dropper = ConnectionDropper(
            self._clients,
            self._owners,
            self._children,
            self._remover,
        )
        return self

    @property
    def write_seam(self) -> WriteSeam:
        """Return the field-mutation seam the authoritative write path uses."""
        return self._seam

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
        """Return non-removed root elements for a scene, read under the lock."""
        with self._lock.read():
            return self._index.scene_roots(scene_id)

    @property
    def reader(self) -> SceneReader:
        """Return the replicator-facing read side — locked snapshots and live ids.

        The replicator depends on exactly this, not the whole store: the
        composition root wires it in, so the replicator never reaches through
        the facade to take a lock.
        """
        return self._reader

    # -- presentation ------------------------------------------------------

    def record_presentation(
        self, scene_id: SceneId, presentation: ScenePresentation
    ) -> None:
        """Remember how a scene was shown, for a later whole-scene resend."""
        with self._lock.write():
            self._frames.record(scene_id, presentation)

    def forget_presentation(self, scene_id: SceneId) -> None:
        """Drop a scene's presentation once a clear blanks it away.

        A whole-display clear empties the scene and blanks the display, and
        nothing repaints it without a re-show recording a fresh presentation, so
        the entry is dead weight. Bounds the frame map on the clear path, as the
        replicator's post-blank reclaim does on the per-scene path.
        """
        with self._lock.write():
            self._frames.forget(scene_id)

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return how a scene was shown, or a self-framed default, read under lock."""
        with self._lock.read():
            return self._frames.presentation_for(scene_id)

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

    # -- authoritative reads (introspection) -------------------------------

    def live_scene_ids(self) -> tuple[SceneId, ...]:
        """Return every scene still holding a non-removed root, read under lock."""
        return self._reader.live_scene_ids()

    def element_count(self, scene_id: SceneId) -> int:
        """Return the count of non-removed elements in a scene, read under lock."""
        with self._lock.read():
            return self._index.element_count(scene_id)

    def scene_owner(self, scene_id: SceneId) -> ConnectionId | None:
        """Return the connection that owns the scene's first root, or None.

        A scene with no live root is unowned; its summary reports no owner.
        """
        with self._lock.read():
            for key, _elem in self._index.scene_root_items(scene_id):
                return self._owners.get(scene_id, key)
        return None

    def client_sessions(self) -> Mapping[ConnectionId, float]:
        """Return each registered Hub session paired with its connect time."""
        return self._clients.sessions()

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

    def show_scene(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        roots: Sequence[WireElement],
        presentation: ScenePresentation,
    ) -> None:
        """Replace a scene's roots and record its presentation under one write lock.

        Batching both writes means a concurrent snapshot never pairs the new roots
        with the old presentation, or the reverse.
        """
        with self._lock.write():
            self.replace_scene(connection_id, scene_id, roots)
            self.record_presentation(scene_id, presentation)

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

    def drop_connection(self, connection_id: ConnectionId) -> frozenset[SceneId]:
        """Tear down a departing connection's roots; return the scenes it touched.

        The caller marks the returned scenes dirty so the replicator blanks the
        ones the drop emptied and repaints the ones a survivor still holds. See
        ``ConnectionDropper``.
        """
        return self._dropper.drop(connection_id)

    # -- private helpers ---------------------------------------------------

    def _remove_root(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Route an ABC root's self-removal back through the authoritative path.

        The installer registers this as the scene-root observer callback; when a
        root flips ``_removed`` it lands here. The store owns the owner tracker,
        so it resolves the owner and runs the removal through ``apply``, sharing
        ownership enforcement and storage teardown with every other remove. An
        already-forgotten root has no owner and needs no teardown.
        """
        owner = self._owners.get(scene_id, element_id)
        if owner is not None:
            self.apply(owner, RemoveElement(scene_id=scene_id, element_id=element_id))


hub_display = HubDisplay()
