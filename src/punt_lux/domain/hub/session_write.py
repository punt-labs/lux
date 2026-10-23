"""SessionWrite — one registry write: the session it replaced and the one it stored.

The registry renews a connection's lease on every write, so a write is always a
``before`` and an ``after`` read at one instant. This value keeps the pair, and it
is what answers the two questions a caller owes the Hub: what the write did to the
Clients menu, and what it did to the connection's listener slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

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
    identified: bool  # whether the write named (or renamed) the connection

    @property
    def menu_change(self) -> PresenceChange:
        """What the Clients menu must hear of this attach.

        Taking the slot over a predecessor's callbacks stops those entries being
        deliverable, which revises the menu even when presence itself held.
        """
        if self.presence == "unchanged" and self.slot == "attached_over_callbacks":
            return "revised"
        return self.presence


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
        cls, before: ClientSession | None, now: float, identity: ClientIdentity | None
    ) -> Self:
        """Renew ``before`` at ``now`` (or start a session), declaring ``identity``."""
        base = before.renewed(now) if before is not None else ClientSession(now)
        return cls(
            before, base if identity is None else base.with_identity(identity), now
        )

    @classmethod
    def attached(
        cls,
        before: ClientSession | None,
        now: float,
        identity: ClientIdentity,
        listener: CallbackListener,
    ) -> Self:
        """Record ``identity`` as in :meth:`recorded`, and seat ``listener``."""
        declared = cls.recorded(before, now, identity)
        return cls(before, declared.after.attached(listener), now)

    @property
    def identified(self) -> bool:
        """Whether the write changed who the session says it is.

        A repository-kind client may register no callback, so presence can hold
        while the connection has just been named; this is the signal that its
        windows are owed a retitle.
        """
        prior = None if self.before is None else self.before.identity
        return prior != self.after.identity

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
            self.identified,
        )
