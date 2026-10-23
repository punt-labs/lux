"""Registration and Detachment -- what a callback write or a teardown did.

Each pairs the outcome the caller branches on with the registry write behind it,
so the lifecycle step that made the write can settle what it owes the Hub
without reading the registry a second time. A write that was refused or found
nothing to do has no write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.hub.registry_outcomes import (
        CallbackRegistration,
        ListenerDetachment,
    )
    from punt_lux.domain.hub.session_write import SessionWrite

__all__ = ["Detachment", "Registration"]


@final
@dataclass(frozen=True, slots=True)
class Registration:
    """What registering a callback did, and the write that took it."""

    outcome: CallbackRegistration
    # None: the registration was refused, so the registry was not written.
    write: SessionWrite | None = None

    @property
    def menu_change(self) -> PresenceChange:
        """What the Clients menu must hear of a registration that took.

        A callback is an entry, so even a session already listed (an agent) has
        a new one to show: it is never ``unchanged``.
        """
        if self.write is None:
            return "unchanged"
        change = self.write.presence
        return "revised" if change == "unchanged" else change


@final
@dataclass(frozen=True, slots=True)
class Detachment:
    """What a teardown found and released, and the write that released it."""

    outcome: ListenerDetachment
    # None: nothing was released -- the session was gone, or a successor holds it.
    write: SessionWrite | None = None

    @property
    def menu_change(self) -> PresenceChange:
        """What the Clients menu must hear of this teardown.

        Entries that stopped being deliverable revise the menu even when the
        session stays listed (an agent that held callbacks).
        """
        if self.write is None:
            return "unchanged"
        change = self.write.presence
        if change == "unchanged" and self.outcome == "released_with_callbacks":
            return "revised"
        return change
