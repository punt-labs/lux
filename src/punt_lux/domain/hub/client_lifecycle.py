"""ClientLifecycle — every transition of a connection's registration, one step each.

A connection arrives, declares who it is, takes a listener slot, registers and
withdraws callbacks, makes contact that renews its lease, and departs. Each is one
critical section under the store's write lock: the registry write, then what it owes
the rest of the Hub. A departure releases ownership and runs the cascade tail, the
sinks included. A write that changes who the Clients menu lists marks the menus and
binds the one shared sink, so no caller is trusted to remember either. The registry
never calls out of its own lock; the store lock is always taken first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_presence import MenuPresence

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from punt_lux.client_host import ClientHost
    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.departure_cascade import DepartureCascade
    from punt_lux.domain.hub.departure_sinks import DepartureSink
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.presence_writes import PresenceWrites
    from punt_lux.domain.hub.registry_outcomes import (
        CallbackRegistration,
        ListenerDetachment,
    )
    from punt_lux.domain.hub.replicator_ports import DirtyMarker
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.hub.session_write import SessionWrite
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.domain.scope import Scope

__all__ = ["ClientLifecycle"]


@final
class ClientLifecycle:
    """Arrival, contact, and departure of the Hub's clients, under the store lock."""

    _writes: PresenceWrites
    _owners: OwnerTracker
    _cascade: DepartureCascade
    _lock: StoreLock
    _presence: MenuPresence
    __slots__ = ("_cascade", "_lock", "_owners", "_presence", "_writes")

    def __new__(
        cls,
        clients: HubClientRegistry,
        owners: OwnerTracker,
        cascade: DepartureCascade,
        lock: StoreLock,
    ) -> Self:
        self = super().__new__(cls)
        self._writes = clients.take_writes()
        self._owners = owners
        self._cascade = cascade
        self._lock = lock
        self._presence = MenuPresence.silent()
        return self

    def exclusive(self) -> AbstractContextManager[bool]:
        """Hold the store lock across a door step and the Hub step beside it.

        The lock every method here takes, reentrant. A caller that must bind a
        Hub writer or an inbox in the same step as a door transition holds it so a
        departure cannot interleave.
        """
        return self._lock.write()

    def present_as(self, marker: DirtyMarker, sink: DepartureSink) -> None:
        """Wire the marker and the one shared menu sink presence changes pay to."""
        with self._lock.write():
            self._presence = MenuPresence(marker, sink)

    def arrive(self, connection_id: ConnectionId, host: ClientHost) -> None:
        """Record the connection's own arrival, and the host it came from."""
        with self._lock.write():
            self._settle(connection_id, self._writes.record(connection_id, None, host))

    def identify(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        host: ClientHost,
    ) -> None:
        """Record the identity the connection declared, and the host it came from."""
        with self._lock.write():
            self._settle(
                connection_id, self._writes.record(connection_id, identity, host)
            )

    def attach(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        listener: CallbackListener,
        host: ClientHost,
    ) -> None:
        """Take the connection's listener slot, recording ``identity`` and ``host``."""
        with self._lock.write():
            attachment = self._writes.attach(connection_id, identity, listener, host)
            self._announce(connection_id, attachment.presence)
            self._resend_scenes(connection_id, owed=attachment.restated)

    def _renew(self, connection_id: ConnectionId, host: ClientHost) -> None:
        """Renew the lease iff registered; every revival is announced and retitled.

        The contact's ``host`` is recorded on the session it renews.
        """
        with self._lock.write():
            write = self._writes.renew_if_registered(connection_id, host)
            if write is not None:
                self._settle(connection_id, write)

    def contact(self, scope: Scope) -> None:
        """Renew the scope's connection if the scope is its own contact.

        A Hub-internal act under an owner's name is not the owner reaching the
        Hub, so it renews nothing.
        """
        if scope.is_contact:
            self._renew(scope.connection_id, scope.client_host)

    def register_callback(
        self,
        connection_id: ConnectionId,
        callback: SessionCallback,
        host: ClientHost,
    ) -> CallbackRegistration:
        """Register ``callback`` on the connection's own leg, and pay what it owes.

        Contact first: the registration renews the lease, and reviving a lapsed
        session retitles its scenes. The leg is read and written under the one
        store hold, so no teardown or reconnect lands between the two. A
        connection with no leg is refused as ``superseded``.
        """
        with self._lock.write():
            self._renew(connection_id, host)
            registration = self._writes.register_callback(connection_id, callback)
            self._announce(connection_id, registration.presence)
            return registration.outcome

    def detach(
        self, connection_id: ConnectionId, listener: CallbackListener
    ) -> ListenerDetachment:
        """Release the connection's leg and callbacks, and mark the withdrawal.

        The session, its lease and its sink survive: a reconnect within the lease
        heals a transient drop. The mark is owed whatever the lease says, since an
        entry a lapse left on the Display is still on it.
        """
        with self._lock.write():
            detachment = self._writes.detach(connection_id, listener)
            self._announce(connection_id, detachment.presence)
            return detachment.outcome

    def arm(self, connection_id: ConnectionId) -> None:
        """Bind the one shared menu sink for the connection; repeating is a no-op."""
        with self._lock.write():
            self._presence.arm(connection_id, self._cascade)

    def bind_sink(self, connection_id: ConnectionId, sink: DepartureSink) -> None:
        """Register ``sink`` as the connection's transport-owned cleanup."""
        with self._lock.write():
            self._cascade.bind_sink(connection_id, sink)

    def depart(self, connection_id: ConnectionId) -> None:
        """Atomically deregister and release everything the connection owned.

        The one step every departure trigger funnels through.
        """
        with self._lock.write():
            relabelled = self._writes.discard(connection_id)
            self._owners.release_all(connection_id)
            self._cascade.run(connection_id)
            self._presence.retitle_scenes(self._owners.scenes_of(relabelled))

    def depart_lapsed(
        self, exclude: frozenset[ConnectionId]
    ) -> frozenset[ConnectionId]:
        """Depart every lapsed connection except ``exclude``; return who left."""
        with self._lock.write():
            reaped = self._writes.reap_lapsed(exclude)
            self._owners.release_departed(reaped.lapsed)
            self._cascade.run_all(reaped.lapsed)
            self._presence.retitle_scenes(self._owners.scenes_of(reaped.relabelled))
            return reaped.lapsed

    def _announce(self, connection_id: ConnectionId, change: PresenceChange) -> None:
        """Pay a presence change's debt -- mark and sink -- in the same step."""
        self._presence.announce(change, connection_id, self._cascade)

    def _settle(self, connection_id: ConnectionId, write: SessionWrite) -> None:
        """Pay what a registry write owes: the menu, and a resend if it restated."""
        self._announce(connection_id, write.presence)
        self._resend_scenes(connection_id, owed=write.restated)

    def _resend_scenes(self, connection_id: ConnectionId, *, owed: bool) -> None:
        """Mark the connection's own scenes dirty if the write restated its session."""
        if owed:
            self._presence.retitle_scenes(self._owners.scenes_of((connection_id,)))
