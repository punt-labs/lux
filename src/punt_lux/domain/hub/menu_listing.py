"""MenuListing — whether the Clients menu lists a session now, and how that changes.

Presence is the lease-filtered set: a session is listed while it is registered,
earns an entry, and its lease is live. An entry leaves when its lease lapses, with
or without a sweep to remove the session, so listing is read against an instant
rather than stored. A write to the registry compares the listing before it with the
listing after it, and the verdict says what the Display is owed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_session import ClientSession

__all__ = ["MenuListing", "PresenceChange"]

# What a registry write did to who the Clients menu lists, as of the instant it
# wrote. ``unchanged``: the Display already shows exactly this. ``gained``: the
# session was not listed (unregistered, lapsed, or earning nothing) and now is.
# ``revised``: it was listed and what the Display shows of it changed -- a
# relabel, or an entry withdrawn. Anything but ``unchanged`` is the caller's cue
# to mark the menus and bind the one shared menu sink.
PresenceChange = Literal["unchanged", "gained", "revised"]


@final
class MenuListing:
    """A session, or the absence of one, as the Clients menu lists it at ``now``."""

    # None: the connection was unregistered, so it lists nothing.
    _session: ClientSession | None
    _now: float
    __slots__ = ("_now", "_session")

    def __new__(cls, session: ClientSession | None, now: float) -> Self:
        self = super().__new__(cls)
        self._session = session
        self._now = now
        return self

    def holds(self) -> bool:
        """Whether the menu lists this session: earning, and its lease in term."""
        session = self._session
        return (
            session is not None
            and session.earns_menu_presence()
            and session.is_live(self._now)
        )

    def change_to(self, after: MenuListing) -> PresenceChange:
        """How the menu differs once ``after`` replaces this listing.

        A renewal that ends a lapse is a gain exactly as a first registration is;
        a re-declaration that changes a listed session's identity is a revision,
        so its entry is relabelled; an entry withdrawn is a revision too.
        """
        if not after.holds():
            return "revised" if self.holds() else "unchanged"
        if not self.holds():
            return "gained"
        return "unchanged" if self._declared() == after._declared() else "revised"

    def _declared(self) -> ClientIdentity | None:
        """The identity the listed session declared; ``None`` for no session."""
        return self._session.identity if self._session is not None else None
