"""ClientSession — one Hub session's connect time, identity, lease, and callbacks.

The registry keys these by ``ConnectionId``. A session exists from the moment a
connection binds — with no identity yet and an unidentified-grace lease — and
gains an identity when the client calls ``identify``. Any authenticated contact
renews the lease; declaring an identity also resets the lease length to the one
its kind declares. Identifying never resets a session's connect time, so age
keeps climbing across a re-identify.

A session's listen leg and menu callbacks live on the session itself, as one
:class:`~punt_lux.domain.hub.listener_slot.ListenerSlot`, so both withdrawals are
structural: when the lease lapses and the registry sweeps the session, the slot
leaves with it in one motion, and so does a teardown that releases it. Keeping
the slot here rather than in the router is what puts the listener and the
callbacks under one lock — the registry's — so installing, committing, and
releasing are each a single critical section. The session decides whether it will
register a callback (``registering``): only an identified, in-lease session
accepts one, so the registry tells the session rather than reaching into its
identity and lease.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.lease_term import LeaseTerms
from punt_lux.domain.hub.listener_slot import ListenerSlot
from punt_lux.domain.hub.session_lease import SessionLease

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.lease_term import LeaseTerm
    from punt_lux.domain.hub.session_callback import SessionCallback

__all__ = ["ClientSession"]


@final
class ClientSession:
    """One Hub session: connect time, identity, lease, and registered callbacks."""

    _connected_at: float
    _identity: ClientIdentity | None
    _lease: SessionLease
    _slot: ListenerSlot
    __slots__ = ("_connected_at", "_identity", "_lease", "_slot")

    def __new__(
        cls,
        connected_at: float,
        identity: ClientIdentity | None = None,
        lease: SessionLease | None = None,
        slot: ListenerSlot | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._connected_at = connected_at
        self._identity = identity
        self._lease = (
            lease if lease is not None else SessionLease.unidentified(connected_at)
        )
        # Absent means the empty slot — the default for a session with no leg yet.
        self._slot = slot if slot is not None else ListenerSlot()
        return self

    @property
    def connected_at(self) -> float:
        """The ``time.monotonic`` reading at which the session first registered."""
        return self._connected_at

    @property
    def identity(self) -> ClientIdentity | None:
        """The declared identity, or ``None`` while the session is unidentified."""
        return self._identity

    @property
    def declared_repo(self) -> str | None:
        """The repository this session declared, or ``None`` if it declared none.

        ``None`` for an unidentified session, a headless CLI, or the app — the
        value the registry's repository projection filters out.
        """
        return self._identity.repo if self._identity is not None else None

    @property
    def callbacks(self) -> tuple[SessionCallback, ...]:
        """The callbacks this session registered, in registration order."""
        return self._slot.callbacks

    @property
    def listener(self) -> CallbackListener | None:
        """The listen leg to wake for this connection, or ``None`` if it holds none."""
        return self._slot.listener

    @property
    def is_push_reachable(self) -> bool:
        """Whether a listen leg occupies this session's slot.

        The registration gate's question: a menu item is delivered by push, so a
        connection with no leg could never be told its item was clicked.
        """
        return self._slot.is_held

    def held_by(self, listener: CallbackListener) -> bool:
        """Whether ``listener`` is the session's current occupant, by identity."""
        return self._slot.held_by(listener)

    def owns_callback(self, callback_id: str) -> bool:
        """Whether this session registered a callback with ``callback_id``."""
        return self._slot.owns(callback_id)

    @property
    def lease_term(self) -> LeaseTerm:
        """How long this session may idle between contacts before it is swept.

        The effective term, not the declared one: a session that named no TTL
        holds its kind's, and luxd's own built-ins hold one that never lapses.
        """
        return LeaseTerms.of(self._lease.ttl_seconds)

    def age(self, now: float) -> float:
        """Seconds since the session connected, clamped so it never goes negative."""
        return max(0.0, now - self._connected_at)

    def is_live(self, now: float) -> bool:
        """Whether the session's lease has not lapsed as of ``now``."""
        return self._lease.is_live(now)

    def renewed(self, now: float) -> ClientSession:
        """Return this session with its lease renewed at ``now``; any contact renews."""
        lease = self._lease.renewed(now)
        return ClientSession(self._connected_at, self._identity, lease, self._slot)

    def with_identity(self, identity: ClientIdentity) -> ClientSession:
        """Return this session carrying ``identity`` and the lease it declared.

        The connect time is kept, and the lease is reset while holding the current
        renewal instant — declaring who you are both attributes the session and sets
        how long it may idle. The length is the identity's declared ``lease_ttl`` when
        it named one, else its kind's default, so a daemon that declares a short TTL
        leaves the menu on its own timer while luxd's built-ins stay permanent.
        """
        lease = SessionLease.for_declared(
            identity.kind, identity.lease_ttl, self._lease.renewed_at
        )
        return ClientSession(self._connected_at, identity, lease, self._slot)

    def with_callback(self, callback: SessionCallback) -> ClientSession:
        """Return this session also owning ``callback``, last write winning by id.

        Identity and lease are unchanged — registering a callback is not a renewal.
        """
        return ClientSession(
            self._connected_at,
            self._identity,
            self._lease,
            self._slot.with_callback(callback),
        )

    def attached(self, listener: CallbackListener) -> ClientSession:
        """Return this session with ``listener`` holding the slot and no callbacks.

        The displaced occupant's callbacks go with it. Two sessions of one identity
        may be live at once — an old one still pumping while its successor connects
        — and leaving the callbacks would keep the departing session's menu entries
        in the bar with every click routed to the newcomer. Nothing else would ever
        withdraw them, because the session that could has lost the slot.
        """
        return ClientSession(
            self._connected_at,
            self._identity,
            self._lease,
            self._slot.occupied_by(listener),
        )

    def detached(self, listener: CallbackListener) -> ClientSession | None:
        """Return this session with an empty slot, or ``None`` if it is not its own.

        The ownership test that keeps a superseded session from removing its
        successor's state. A session whose socket has gone may still be suspended
        in its teardown while a reconnect completes an entire connect; when it
        resumes, it is no longer the occupant, and it must remove nothing. ``None``
        is that decline — the stale case, a normal outcome rather than a failure.

        The listener and the callbacks go together, so no reader can observe a
        callback whose listener has already been cleared.
        """
        return (
            ClientSession(
                self._connected_at, self._identity, self._lease, self._slot.released()
            )
            if self._slot.held_by(listener)
            else None
        )

    def registering(
        self, callback: SessionCallback, now: float
    ) -> ClientSession | None:
        """Return a copy owning ``callback``, or ``None`` if the session declines.

        A session accepts a callback only while it is identified and in lease; an
        unidentified or lapsed session declines. ``None`` is that decline — a normal
        discriminated outcome the registry maps to an identify challenge, not a
        value-production failure — so the registry stores the returned session or
        leaves the store untouched without reaching into identity and lease itself.
        """
        accepted = self._identity is not None and self.is_live(now)
        return self.with_callback(callback) if accepted else None
