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
- ``FrameExpiry`` — per-frame TTL deadlines; armed at ``show_scene`` and swept by
  ``expire_due`` under the store lock, so a re-show and an expiry never race.
- ``SubtreeInstaller`` / ``SubtreeRemover`` — the mirror install and teardown
  walks ``apply`` delegates to.

A scene's presentation is kept until the scene is blanked away or re-shown, so an
emptied scene can still be blanked into the frame it was shown in; once the
replicator delivers that blank it reclaims the presentation. ``drop_connection``
forgets a departing connection as a Hub client but leaves its scenes standing:
a session's UI survives the session, to be removed later by a frame close, a
clear, or a TTL — never by the disconnect itself.

Every write runs under ``StoreLock`` so a snapshot never reads a half-applied
scene. Every read takes the lock in read mode too — the replicator's crossing
reads through ``scene_snapshot`` and ``live_scene_ids``, and the facade's own
``scene_roots`` and ``presentation_for`` — so the lock discipline is the store's
own behavior and never escapes to the caller.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.element_index import (
    ElementIndex,
    UnknownElementError,
    UnknownSceneError,
)
from punt_lux.domain.hub.frame_expiry import FrameExpiry
from punt_lux.domain.hub.frame_lifecycle import FrameLifecycle
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_reads import HubReads
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
    from collections.abc import Callable, Mapping, Sequence
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

    Facade over typed collaborators. State invariants (established at ``apply``
    time, trusted thereafter):

    - Every Element installed has a known owner ``ConnectionId``.
    - A scene-root ABC Element (``parent_id=None``) carries a HubDisplay-owned
      observer; flipping ``_removed`` calls back into ``apply(RemoveElement(...))``.
    - A child Element (``parent_id`` set) is observed by its parent composite, not
      by HubDisplay, which drives its ``apply(RemoveElement(...))`` instead.

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
    _reads: HubReads
    _frame_lifecycle: FrameLifecycle

    def __new__(cls, clock: Callable[[], float] = time.monotonic) -> Self:
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
        self._reads = HubReads(self._index, self._owners, self._clients, self._lock)
        self._frame_lifecycle = FrameLifecycle(
            self._frames, self._remover, FrameExpiry(clock), self._lock
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
        return self._reads.scene_roots(scene_id)

    @property
    def reader(self) -> SceneReader:
        """Return the replicator-facing read side — locked snapshots and live ids.

        The replicator depends on exactly this, not the whole store: the
        composition root wires it in, so the replicator never reaches through
        the facade to take a lock.
        """
        return self._reader

    @property
    def frames(self) -> FrameLifecycle:
        """Return the frame authority — presentations, TTL expiry, and teardown.

        Callers reach how a scene is framed (``presentation_for``), close a frame
        (``remove_frame``), and sweep expiry (``expire_due``) through this
        sub-object, exposed like ``reader`` so the facade carries no per-frame
        delegator.
        """
        return self._frame_lifecycle

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
        return self._reads.element_count(scene_id)

    def scene_owners(self, scene_id: SceneId) -> tuple[ConnectionId, ...]:
        """Return each scene's distinct root owners, first-appearance order."""
        return self._reads.scene_owners(scene_id)

    def client_sessions(self) -> Mapping[ConnectionId, float]:
        """Return each registered Hub session paired with its connect time."""
        return self._reads.client_sessions()

    @trace
    def replace_scene(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        roots: Sequence[WireElement],
    ) -> None:
        """Replace ``scene_id`` wholesale with ``roots`` owned by ``connection_id``.

        The scene is the unit of replacement: a re-show first tears down every
        root the scene holds — whatever connection owns it — then installs the
        new roots through the normal ``apply(AddElement(...))`` path so ownership,
        root observers, and child indexes are rebuilt in one place. Clearing every
        root regardless of owner is the whole-UI-resend contract: the latest show
        of a scene_id defines the whole scene, so an orphan left by a departed
        session is cleared by the next show, never stranded beside the new roots.
        """
        with self._lock.write():
            self.register_client(connection_id)
            self._remover.drop_scene_roots(scene_id)
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
        *,
        ttl_seconds: float | None = None,
    ) -> None:
        """Replace a scene's roots and show it into its frame with a TTL.

        Both writes share one write lock, so a concurrent snapshot never pairs new
        roots with an old presentation and a concurrent expiry sweep never races the
        deadline arm (``FrameLifecycle.present`` records the presentation and arms
        the deadline as one step). A ``ttl_seconds`` of None clears any prior
        deadline, making a re-show without a TTL permanent.
        """
        with self._lock.write():
            self.replace_scene(connection_id, scene_id, roots)
            self._frame_lifecycle.present(scene_id, presentation, ttl_seconds)

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

    # -- cleanup trigger ---------------------------------------------------

    def drop_connection(self, connection_id: ConnectionId) -> None:
        """Forget a departing connection as a Hub client, leaving its scenes.

        A session's UI survives the session: the connection's roots stay
        installed and stay owned by its id (so a later frame close, clear, or TTL
        can still remove them). Only the client registration is dropped, so the
        session no longer appears among the live Hub clients.
        """
        self._clients.discard(connection_id)

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
