"""ClientSession — one Hub session's connect time, identity, lease, and callbacks.

The registry keys these by ``ConnectionId``. A session exists from the moment a
connection binds — with no identity yet and an unidentified-grace lease — and
gains an identity when the client calls ``identify``. Any authenticated contact
renews the lease; declaring an identity also resets the lease length to the one
its kind declares. Identifying never resets a session's connect time, so age
keeps climbing across a re-identify.

A session's menu callbacks live on the session itself, so withdrawal is
structural: when the lease lapses and the registry sweeps the session, its
callbacks leave with it in one motion — there is no separate callback store to
reap. The session decides whether it will register a callback (``registering``):
only an identified, in-lease session accepts one, so the registry tells the
session rather than reaching into its identity and lease.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.session_lease import SessionLease

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.session_callback import SessionCallback

__all__ = ["ClientSession"]


@final
class ClientSession:
    """One Hub session: connect time, identity, lease, and registered callbacks."""

    _connected_at: float
    _identity: ClientIdentity | None
    _lease: SessionLease
    _callbacks: tuple[SessionCallback, ...]
    __slots__ = ("_callbacks", "_connected_at", "_identity", "_lease")

    def __new__(
        cls,
        connected_at: float,
        identity: ClientIdentity | None = None,
        lease: SessionLease | None = None,
        callbacks: tuple[SessionCallback, ...] = (),
    ) -> Self:
        self = super().__new__(cls)
        self._connected_at = connected_at
        self._identity = identity
        self._lease = (
            lease if lease is not None else SessionLease.unidentified(connected_at)
        )
        self._callbacks = callbacks
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
        return self._callbacks

    def owns_callback(self, callback_id: str) -> bool:
        """Whether this session registered a callback with ``callback_id``."""
        return any(callback.id == callback_id for callback in self._callbacks)

    def age(self, now: float) -> float:
        """Seconds since the session connected, clamped so it never goes negative."""
        return max(0.0, now - self._connected_at)

    def is_live(self, now: float) -> bool:
        """Whether the session's lease has not lapsed as of ``now``."""
        return self._lease.is_live(now)

    def renewed(self, now: float) -> ClientSession:
        """Return this session with its lease renewed at ``now``; any contact renews."""
        lease = self._lease.renewed(now)
        return ClientSession(self._connected_at, self._identity, lease, self._callbacks)

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
        return ClientSession(self._connected_at, identity, lease, self._callbacks)

    def with_callback(self, callback: SessionCallback) -> ClientSession:
        """Return this session with ``callback`` registered, last write winning by id.

        A callback whose id the session already holds replaces the earlier one, so
        the session never carries two callbacks under one id; a new id is appended.
        Identity and lease are unchanged — registering a callback is not a renewal.
        """
        kept = tuple(c for c in self._callbacks if c.id != callback.id)
        return ClientSession(
            self._connected_at, self._identity, self._lease, (*kept, callback)
        )

    def without_callbacks(self) -> ClientSession:
        """Return this session owning no callbacks, its identity and lease intact.

        What a session's menu items are worth when the connection they were
        registered on goes away: nothing. A callback is delivered by push, so it
        outlives its listener only as an entry the user can click into silence.
        The session itself survives — the same identity reconnecting re-registers
        what it still wants — so only the callbacks are dropped.
        """
        return ClientSession(self._connected_at, self._identity, self._lease, ())

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
