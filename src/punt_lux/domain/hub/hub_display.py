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
- ``FrameExpiry`` — per-frame TTL deadlines, swept under the store lock so a
  re-show and an expiry never race.
- ``SubtreeInstaller`` / ``SubtreeRemover`` — the install and teardown walks.

A scene's presentation is kept until blanked away or re-shown, so an emptied
scene can still be blanked into its frame; the replicator reclaims it after.
Departure (``drop_connection``, a lapsed lease, or ``apply``'s own sweep of
others) releases a connection's ownership but never tears its content down.

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
from punt_lux.domain.hub.dismissal_walk import DismissalWalk
from punt_lux.domain.hub.element_index import (
    ElementIndex,
    UnknownElementError,
    UnknownSceneError,
)
from punt_lux.domain.hub.frame_expiry import FrameExpiry
from punt_lux.domain.hub.frame_lifecycle import FrameLifecycle
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_reads import HubReads
from punt_lux.domain.hub.owner import Owner
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.quarantine_registry import QuarantineRegistry
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.root_removal_router import RootRemovalRouter
from punt_lux.domain.hub.scene_eviction import SceneEviction
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

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord

    QuarantineClearedObserver = Callable[[SceneId], None]

__all__ = [
    "HubDisplay",
    "HubOwnershipError",
    "UnknownElementError",
    "UnknownSceneError",
    "hub_display",
]


class HubDisplay:
    """Hub-side authoritative store of Elements, owners, and clients.

    Facade over typed collaborators: invariants are established at ``apply``
    time and trusted thereafter (every installed Element has a known owner;
    a scene-root ABC Element's observer routes ``_removed`` back through
    ``apply``). Tests construct their own ``HubDisplay()``; the module also
    exposes ``hub_display`` as the production singleton.
    """

    _index: ElementIndex
    _owners: OwnerTracker
    _roots: RootRegistry
    _children: ChildIndex
    _dismissal: DismissalWalk
    _clients: HubClientRegistry
    _frames: ScenePresentationRegistry
    _seam: WriteSeam
    _remover: SubtreeRemover
    _installer: SubtreeInstaller
    _lock: StoreLock
    _reader: SceneReader
    _reads: HubReads
    _frame_lifecycle: FrameLifecycle
    _quarantine: QuarantineRegistry
    _quarantine_cleared_observers: list[QuarantineClearedObserver]
    _eviction: SceneEviction

    def __new__(cls, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        self._index = ElementIndex()
        self._clients = HubClientRegistry(clock)
        self._owners = OwnerTracker()
        self._roots = RootRegistry()
        self._children = ChildIndex()
        self._dismissal = DismissalWalk(self._index, self._children)
        self._frames = ScenePresentationRegistry()
        self._quarantine = QuarantineRegistry()
        self._quarantine_cleared_observers = []
        self._seam = WriteSeam(self._index)
        self._remover = SubtreeRemover(
            self._index, self._owners, self._roots, self._children
        )
        # The one path every scene-teardown flows through — replace_scene,
        # frame close, and TTL expiry — so quarantine never outlives the
        # scene it was attached to. Uses the same _lift_quarantine helper
        # the owner-driven paths do, so the observer cascade (tally reset,
        # etc.) fires uniformly on every clear.
        self._eviction = SceneEviction(self._remover, self._lift_quarantine)
        root_removal = RootRemovalRouter(self._owners, self.apply)
        self._installer = SubtreeInstaller(
            self._index,
            self._owners,
            self._roots,
            self._children,
            root_removal.route,
        )
        self._lock = StoreLock()
        self._frame_lifecycle = FrameLifecycle(
            self._frames, self._eviction, FrameExpiry(clock), self._lock
        )
        self._reader = SceneReader(self._index, self._frame_lifecycle, self._lock)
        self._reads = HubReads(self._index, self._owners, self._clients, self._lock)
        return self

    @property
    def write_seam(self) -> WriteSeam:
        """Return the field-mutation seam the authoritative write path uses."""
        return self._seam

    def write_lock(self) -> AbstractContextManager[bool]:
        """Hold the store lock across an external mutation batch; reentrant."""
        return self._lock.write()

    # -- clients registry --------------------------------------------------

    def register_client(self, connection_id: ConnectionId) -> None:
        """Record a connection's own arrival as a client, renewing its lease."""
        self._clients.record(connection_id)

    def identify_client(
        self, connection_id: ConnectionId, identity: ClientIdentity
    ) -> None:
        """Record the identity a connection declared, registering it if new."""
        self._clients.record(connection_id, identity)

    def is_client(self, connection_id: ConnectionId) -> bool:
        """Return True if the connection is currently registered."""
        return self._clients.session_of(connection_id) is not None

    @property
    def clients(self) -> HubClientRegistry:
        """Return the session registry — identity, lease, and callback authority."""
        return self._clients

    # -- index access ------------------------------------------------------

    def scene_roots(self, scene_id: SceneId) -> list[WireElement]:
        """Return non-removed root elements for a scene, read under the lock."""
        return self._reads.scene_roots(scene_id)

    @property
    def reader(self) -> SceneReader:
        """Return the replicator-facing read side — locked snapshots and live ids."""
        return self._reader

    @property
    def frames(self) -> FrameLifecycle:
        """Return the frame authority — presentations, TTL expiry, and teardown."""
        return self._frame_lifecycle

    def resolve(self, scene_id: SceneId, element_id: ElementId) -> WireElement:
        """Return the indexed Element or raise ``UnknownElementError``."""
        return self._index.lookup(scene_id, element_id)

    def owner_of(self, scene_id: SceneId, element_id: ElementId) -> ConnectionId | None:
        """Return the element's owner, or ``None`` if installed but unowned.

        ``None`` is a distinct, valid state (a departure released it), not an
        error; ``UnknownElementError`` is for an element the index never held.
        """
        with self._lock.read():
            if not self._index.contains(scene_id, element_id):
                raise UnknownElementError(scene_id=scene_id, element_id=element_id)
            owner = self._owners.get(scene_id, element_id)
            return owner.connection_id if owner is not None else None

    @property
    def dismissal(self) -> DismissalWalk:
        """Return the ancestor-dismissal walk over the index and child edges."""
        return self._dismissal

    def elements_owned_by(
        self,
        connection_id: ConnectionId,
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        with self._lock.read():
            return self._owners.keys_for(connection_id)

    # -- authoritative reads (introspection) -------------------------------

    def live_scene_ids(self) -> tuple[SceneId, ...]:
        """Return every non-quarantined scene still holding a non-removed root.

        The replication-facing read: quarantined scenes are excluded at the
        source, so no caller — including the reconnect reconciliation hook —
        re-marks one for a fresh Display to crash on again. Introspection
        uses :meth:`all_scene_ids` instead, which keeps a quarantined scene
        visible.
        """
        with self._lock.read():
            quarantined = self._quarantine.quarantined_ids()
            return tuple(
                s for s in self._reader.live_scene_ids() if s not in quarantined
            )

    def all_scene_ids(self) -> tuple[SceneId, ...]:
        """Return every scene still holding a non-removed root, quarantined or not.

        The introspection-facing read — quarantine is a replication decision,
        not a deletion, unlike :meth:`live_scene_ids`.
        """
        return self._reader.live_scene_ids()

    def element_count(self, scene_id: SceneId) -> int:
        """Return the count of non-removed elements in a scene, read under lock."""
        return self._reads.element_count(scene_id)

    def scene_owners(self, scene_id: SceneId) -> tuple[Owner, ...]:
        """Return each scene's distinct root owners, first-appearance order."""
        return self._reads.scene_owners(scene_id)

    def client_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return each registered Hub session paired with its session record."""
        return self._reads.client_sessions()

    def client_repos(self) -> frozenset[str]:
        """Return the distinct repositories the identified sessions declared."""
        return self._clients.repos()

    # -- quarantine ----------------------------------------------------------

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        """Quarantine ``scene_id``: stop replicating it, keep it for inspection.

        Called by :class:`~punt_lux.domain.hub.crash_attribution.CrashAttribution`
        through the ``QuarantinePort`` this class satisfies structurally. The
        scene stays installed — quarantine is a replication decision, not a
        deletion — so an agent can still ``inspect_scene`` it to see what it built.

        Runs under the store write lock, paired with the readers below and
        with the check-then-write sequence in
        :meth:`~punt_lux.operations.scenes.SceneOperations.update`: an update
        that saw "not quarantined" cannot then race with this write and land a
        patch on a now-quarantined scene, because both hold the same
        reentrant lock across the compound decision.
        """
        with self._lock.write():
            self._quarantine.quarantine(scene_id, record)

    def is_quarantined(self, scene_id: SceneId) -> bool:
        """Return whether ``scene_id`` currently carries a quarantine record."""
        with self._lock.read():
            return self._quarantine.is_quarantined(scene_id)

    def quarantine_record(self, scene_id: SceneId) -> QuarantineRecord | None:
        """Return the scene's quarantine record, or None if not quarantined."""
        with self._lock.read():
            return self._quarantine.record_for(scene_id)

    def add_quarantine_cleared_observer(
        self, observer: QuarantineClearedObserver
    ) -> None:
        """Register a callback for quarantine-lift; runs under the lock, no I/O."""
        with self._lock.write():
            self._quarantine_cleared_observers.append(observer)

    def _lift_quarantine(self, scene_id: SceneId) -> None:
        """Clear ``scene_id``'s quarantine and notify observers. Caller locks."""
        if not self._quarantine.is_quarantined(scene_id):
            return
        self._quarantine.clear(scene_id)
        for observer in self._quarantine_cleared_observers:
            observer(scene_id)

    @trace
    def replace_scene(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        roots: Sequence[WireElement],
    ) -> None:
        """Replace ``scene_id`` wholesale with ``roots`` owned by ``connection_id``.

        The scene is the unit of replacement: a re-show tears down every root the
        scene holds — whatever connection owns it — then re-installs through the
        normal ``apply(AddElement(...))`` path, rebuilding ownership, observers, and
        child indexes in one place. The latest show defines the whole scene, so an
        orphan from a departed session is cleared, never stranded beside new roots.
        A write registers nobody: a session comes only from its own arrival.

        A wholesale replace is a *different tree*, presumed fixed, so it lifts
        any quarantine the scene carried — the normal recovery path an owner
        takes after reading a quarantine record and fixing the offending
        element. Routes through the eviction adapter so the observer cascade
        (in particular, resetting the attribution tally so a re-crash needs
        the full threshold again) fires here exactly as it does for a frame
        close or a TTL expiry.
        """
        with self._lock.write():
            self._eviction.drop_scene_roots(scene_id)
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

        Both writes share one write lock, so a snapshot never pairs new roots with
        an old presentation and an expiry sweep never races the deadline arm. A
        ``ttl_seconds`` of None clears any prior deadline, making a re-show permanent.
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

        ``AddElement`` installs the root then recurses into composite children via
        the Composite Protocol, so a child Button buried in a Dialog lands in the
        index and later clicks — keyed by ``(scene, element_id)`` — resolve.

        ``SetProperty`` and ``RemoveElement`` mutate an already-installed element and
        require the caller to own it, mirroring ``Display.apply``'s ownership
        enforcement so a misbehaving client cannot evict another client's state.

        Three things happen in order, one atomic step: the caller's own lease
        renews first if it already holds one (a write still registers
        nobody — an unregistered or already-departed caller proceeds
        unregistered, as always). Every *other* lapsed connection is then
        departed and released. Only then does the ownership check run — so
        any live claimant is never blocked by a grip this same step just let
        go of.
        """
        with self._lock.write():
            self._clients.renew_if_registered(connection_id)
            self._depart_lapsed(exclude=frozenset({connection_id}))
            match update:
                case AddElement(scene_id=sid, parent_id=pid, element=elem):
                    session = self._clients.session_of(connection_id)
                    owner = Owner.from_session(connection_id, session)
                    self._installer.install(sid, elem, parent_id=pid, owner=owner)
                case SetProperty(
                    scene_id=sid, element_id=eid, field=field, value=value
                ):
                    self._owners.require_ownership(sid, eid, connection_id)
                    self._seam.set_property(sid, eid, field, value)
                case RemoveElement(scene_id=sid, element_id=eid):
                    self._owners.require_ownership(sid, eid, connection_id)
                    self._remover.remove_subtree(sid, eid)
                    if not self._index.scene_roots(sid):
                        # An explicit clear (or any removal) that empties the
                        # scene removes its quarantine along with it — a scene
                        # with nothing to render has nothing left to be
                        # quarantined from. Routes through the shared helper
                        # so the observer cascade (tally reset, etc.) fires
                        # exactly as on any other quarantine-clear path.
                        self._lift_quarantine(sid)

    # -- departure: the single deregister-and-release coordinator -----------

    def drop_connection(self, connection_id: ConnectionId) -> None:
        """Depart ``connection_id`` unconditionally, releasing what it owned.

        The graceful-disconnect and SDK-idle-reap path — no lease condition
        gates it, unlike a lapse-triggered departure.
        """
        with self._lock.write():
            self._depart(connection_id)

    def reap_lapsed_leases(self) -> frozenset[ConnectionId]:
        """Depart every connection whose lease has lapsed; return who left.

        The background timer's hook — independent of any read, any other
        connection's write, and any disconnect signal.
        """
        return self._depart_lapsed(exclude=frozenset())

    def _depart_lapsed(
        self, *, exclude: frozenset[ConnectionId]
    ) -> frozenset[ConnectionId]:
        """Depart every lapsed connection except ``exclude``; return who left."""
        with self._lock.write():
            lapsed = self._clients.reap_lapsed_locked(exclude)
            self._owners.release_departed(lapsed)
            return lapsed

    def _depart(self, connection_id: ConnectionId) -> None:
        """Atomically deregister and release everything ``connection_id`` owned.

        The one step every departure trigger funnels through. Caller holds
        the store write lock.
        """
        self._clients.discard(connection_id)
        self._owners.release_all(connection_id)


hub_display = HubDisplay()
