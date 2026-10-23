"""SessionWrite — one registry write: the session it replaced and the one it stored.

The registry renews a connection's lease on every write, so a write is always a
``before`` and an ``after`` read at one instant. This value keeps the pair, and it
is what answers the two questions a caller owes the Hub: what the write did to the
Clients menu, and what it did to the connection's listener slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.client_host import NO_HOSTS, ClientHost
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.menu_listing import MenuListing

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.hub.registry_outcomes import ListenerAttachment

__all__ = ["Attachment", "SessionWrite"]


@final
@dataclass(frozen=True, slots=True)
class Attachment:
    """What taking a connection's listener slot did: to the slot, and to the menu."""

    slot: ListenerAttachment
    presence: PresenceChange
    restated: bool  # whether the write changed who the session is or where from


@final
@dataclass(frozen=True, slots=True)
class SessionWrite:
    """The session a write replaced (``None`` if new), the one it stored, and when."""

    # None: the connection was unregistered before this write.
    before: ClientSession | None
    after: ClientSession
    now: float

    @classmethod
    def recorded(
        cls,
        before: ClientSession | None,
        now: float,
        identity: ClientIdentity | None,
        host: ClientHost,
    ) -> Self:
        """Renew ``before`` at ``now`` (or start a session), declaring ``identity``.

        ``host`` is where the transport observed the contact from; it is recorded
        beside the identity, in the same write, so a resend triggered by
        identification already carries it.
        """
        base = before.renewed(now) if before is not None else ClientSession(now)
        seen = base.observed_from(host)
        return cls(
            before, seen if identity is None else seen.with_identity(identity), now
        )

    def seated(self, listener: CallbackListener) -> Self:
        """This write, with ``listener`` also seated in the stored session's slot.

        The attach is the declaration plus the seating, so it is the recorded
        write that seats the listener: it already holds the session before and
        after, and when, so nothing is threaded through a second constructor.
        """
        return type(self)(self.before, self.after.attached(listener), self.now)

    @property
    def restated(self) -> bool:
        """Whether the write changed who the session is, where from, or that it lives.

        A repository-kind client may register no callback, so presence can hold
        while the connection has just been named; this is the signal that what
        the Hub shows of it -- its title and its host -- is owed a resend. A
        new distinct host counts: the popup's host row would otherwise stay stale.
        """
        before = self.before
        prior_identity = None if before is None else before.identity
        prior_hosts = NO_HOSTS if before is None else before.client_hosts
        return (
            prior_identity != self.after.identity
            or prior_hosts != self.after.client_hosts
            or self.revived
        )

    @property
    def revived(self) -> bool:
        """Whether the write ended a lapse: the session was not live, and now is.

        Labels resolve from live sessions only, so a frame whose owner lapsed
        unswept may hold a stale title; reviving the owner owes its scenes a
        resend whatever the menu heard, and whether or not it earns an entry.
        """
        before = self.before
        return (
            before is not None
            and not before.is_live(self.now)
            and self.after.is_live(self.now)
        )

    @property
    def presence(self) -> PresenceChange:
        """How the write changed who the Clients menu lists."""
        return MenuListing(self.before, self.now).change_to(
            MenuListing(self.after, self.now)
        )

    @property
    def attachment(self) -> Attachment:
        """The write read as taking the listener slot."""
        over_callbacks = self.before is not None and bool(self.before.callbacks)
        return Attachment(
            "attached_over_callbacks" if over_callbacks else "attached",
            self.presence,
            self.restated,
        )
