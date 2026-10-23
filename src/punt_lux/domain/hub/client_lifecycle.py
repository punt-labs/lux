"""ClientLifecycle — every transition of a connection's registration, one step each.

A connection arrives, declares who it is, takes a listener slot, makes contact that
renews its lease, and departs. Each is one critical section under the store's write
lock: the registry write, then what the write owes the rest of the Hub. A departure
releases the connection's ownership and runs the cascade tail, the sinks included. A
write that changes who the Clients menu lists marks the menus and binds the one
shared menu sink, so no caller is trusted to remember either. The registry never
calls out of its own lock; the store lock is always taken first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_presence import MenuPresence

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.departure_cascade import DepartureCascade
    from punt_lux.domain.hub.departure_sinks import DepartureSink
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.replicator_ports import DirtyMarker
    from punt_lux.domain.hub.session_write import SessionWrite
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientLifecycle"]


@final
class ClientLifecycle:
    """Arrival, contact, and departure of the Hub's clients, under the store lock."""

    _clients: HubClientRegistry
    _owners: OwnerTracker
    _cascade: DepartureCascade
    _lock: StoreLock
    _presence: MenuPresence
    __slots__ = ("_cascade", "_clients", "_lock", "_owners", "_presence")

    def __new__(
        cls,
        clients: HubClientRegistry,
        owners: OwnerTracker,
        cascade: DepartureCascade,
        lock: StoreLock,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
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

    def arrive(self, connection_id: ConnectionId) -> None:
        """Record the connection's own arrival, renewing its lease."""
        with self._lock.write():
            self._settle(connection_id, self._clients.record(connection_id))

    def identify(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        peer: str | None = None,  # PY-TS-14: a transport may report no peer
    ) -> None:
        """Record the identity the connection declared, and the host it came from."""
        with self._lock.write():
            self._settle(
                connection_id, self._clients.record(connection_id, identity, peer)
            )

    def attach(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        listener: CallbackListener,
        peer: str | None = None,  # PY-TS-14: a transport may report no peer
    ) -> None:
        """Take the connection's listener slot, recording ``identity`` and ``peer``."""
        with self._lock.write():
            attachment = self._clients.legs.attach(
                connection_id, identity, listener, peer
            )
            self._announce(connection_id, attachment.menu_change)
            self._retitle(connection_id, named=attachment.identified)

    def renew(self, connection_id: ConnectionId) -> None:
        """Renew the lease iff registered; reviving a lapsed agent is announced."""
        with self._lock.write():
            self._announce(
                connection_id, self._clients.renew_if_registered(connection_id)
            )

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
            relabelled = self._clients.discard(connection_id)
            self._owners.release_all(connection_id)
            self._cascade.run(connection_id)
            self._presence.scenes_renamed(self._owners.scenes_of(relabelled))

    def depart_lapsed(
        self, exclude: frozenset[ConnectionId]
    ) -> frozenset[ConnectionId]:
        """Depart every lapsed connection except ``exclude``; return who left."""
        with self._lock.write():
            reaped = self._clients.reap_lapsed_locked(exclude)
            self._owners.release_departed(reaped.lapsed)
            self._cascade.run_all(reaped.lapsed)
            self._presence.scenes_renamed(self._owners.scenes_of(reaped.relabelled))
            return reaped.lapsed

    def _announce(self, connection_id: ConnectionId, change: PresenceChange) -> None:
        """Pay a presence change's debt -- mark and sink -- in the same step."""
        self._presence.announce(change, connection_id, self._cascade)

    def _settle(self, connection_id: ConnectionId, write: SessionWrite) -> None:
        """Pay what a registry write owes: the menu, and a retitle if it named."""
        self._announce(connection_id, write.presence)
        self._retitle(connection_id, named=write.identified)

    def _retitle(self, connection_id: ConnectionId, *, named: bool) -> None:
        """Mark the connection's own scenes dirty if it has just been named."""
        if named:
            self._presence.scenes_renamed(self._owners.scenes_of((connection_id,)))
