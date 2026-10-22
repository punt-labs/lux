"""HubDisplay — facade over the Hub-side Element/owner/client store.

``HubDisplay`` is the single public surface the rest of the system talks to for
Hub-side scene state. Internally it composes typed collaborators, each with one
responsibility:

- ``ElementIndex`` — ``(scene_id, element_id) → Element`` lookup.
- ``OwnerTracker`` — every Element's owning ``ConnectionId``.
- ``RootRegistry`` — scene-root ABC Elements in the property-Observer cascade.
- ``ChildIndex`` — parent → children edges for one-walk descendant removal.
- ``ClientLifecycle`` — client arrival, contact, and departure (it owns the
  ``HubClientRegistry`` and the departure cascade).
- ``ScenePresentationRegistry`` — how each live scene is framed for a resend.
- ``FrameExpiry`` — per-frame TTL deadlines, swept under the store lock so a
  re-show and an expiry never race.
- ``SubtreeInstaller`` / ``SubtreeRemover`` — the install and teardown walks.

A scene's presentation is kept until blanked away or re-shown, so an emptied
scene can still be blanked into its frame; the replicator reclaims it after.
Departure (``ClientLifecycle.depart``, a lapsed lease, or ``apply``'s own sweep of
others) releases a connection's ownership but never tears its content down.

Every write runs under ``StoreLock`` so a snapshot never reads a half-applied
scene. Every read takes the lock in read mode too — the replicator's crossing
reads through ``scene_snapshot`` and ``live_scene_ids`` and the collaborators in
``HubParts`` — so the lock discipline is the store's
own behavior and never escapes to the caller.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.client_lifecycle_factory import ClientLifecycleFactory
from punt_lux.domain.hub.dismissal_walk import DismissalWalk
from punt_lux.domain.hub.element_index import (
    ElementIndex,
    UnknownElementError,
    UnknownSceneError,
)
from punt_lux.domain.hub.frame_expiry import FrameExpiry
from punt_lux.domain.hub.frame_lifecycle import FrameLifecycle
from punt_lux.domain.hub.hub import Hub, hub as default_hub
from punt_lux.domain.hub.hub_parts import HubParts
from punt_lux.domain.hub.hub_reads import HubReads
from punt_lux.domain.hub.owner import Owner
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.root_removal_router import RootRemovalRouter
from punt_lux.domain.hub.scene_eviction import SceneEviction
from punt_lux.domain.hub.scene_presentation import ScenePresentationRegistry
from punt_lux.domain.hub.scene_quarantine import SceneQuarantine
from punt_lux.domain.hub.scene_snapshot import SceneReader
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.hub.subtree_installer import SubtreeInstaller
from punt_lux.domain.hub.subtree_remover import SubtreeRemover
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.scene_presentation import ScenePresentation

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
    _seam: WriteSeam
    _remover: SubtreeRemover
    _installer: SubtreeInstaller
    _lock: StoreLock
    _frame_lifecycle: FrameLifecycle
    _quarantine: SceneQuarantine
    _eviction: SceneEviction
    _lifecycle: ClientLifecycle
    _clients: HubClientRegistry
    _parts: HubParts

    def __new__(
        cls, clock: Callable[[], float] = time.monotonic, hub: Hub = default_hub
    ) -> Self:
        self = super().__new__(cls)
        self._lock = StoreLock()
        self._quarantine = SceneQuarantine(self._lock)
        self._index = ElementIndex()
        self._owners = OwnerTracker()
        roots = RootRegistry()
        children = ChildIndex()
        self._seam = WriteSeam(self._index)
        self._remover = SubtreeRemover(self._index, self._owners, roots, children)
        # The one path every scene-teardown flows through — replace_scene,
        # frame close, and TTL expiry — so quarantine never outlives the
        # scene it was attached to. Uses the same SceneQuarantine.lift helper
        # the owner-driven paths do, so the observer cascade (tally reset,
        # etc.) fires uniformly on every clear.
        self._eviction = SceneEviction(self._remover, self._quarantine.lift)
        root_removal = RootRemovalRouter(self._owners, self.apply)
        self._installer = SubtreeInstaller(
            self._index, self._owners, roots, children, root_removal.route
        )
        factory = ClientLifecycleFactory(hub, clock)
        self._clients = factory.registry
        self._lifecycle = factory.build(self._owners, self._lock)
        self._frame_lifecycle = FrameLifecycle(
            ScenePresentationRegistry(), self._eviction, FrameExpiry(clock), self._lock
        )
        self._parts = HubParts(
            lifecycle=self._lifecycle,
            clients=self._clients,
            reads=HubReads(self._index, self._owners, self._clients, self._lock),
            reader=SceneReader(
                self._index, self._frame_lifecycle, self._lock, self._quarantine
            ),
            frames=self._frame_lifecycle,
            quarantines=self._quarantine,
            dismissal=DismissalWalk(self._index, children),
            seam=self._seam,
        )
        return self

    @property
    def parts(self) -> HubParts:
        """Return the wired collaborators; callers hold the one they use."""
        return self._parts

    def write_lock(self) -> AbstractContextManager[bool]:
        """Hold the store lock across an external mutation batch; reentrant."""
        return self._lock.write()

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
            self._lifecycle.renew(connection_id)
            self._lifecycle.depart_lapsed(frozenset({connection_id}))
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
                        self._quarantine.lift(sid)


hub_display = HubDisplay()
