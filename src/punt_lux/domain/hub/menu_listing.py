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
    from punt_lux.domain.hub.session_callback import SessionCallback

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

    def _earned(self) -> bool:
        """Whether this session earns an entry, ignoring whether its lease is live."""
        return self._session is not None and self._session.earns_menu_presence()

    def change_to(self, after: MenuListing) -> PresenceChange:
        """How the menu differs once ``after`` replaces this listing.

        A renewal that ends a lapse is a gain exactly as a first registration is;
        a re-declaration that changes a listed session's identity is a revision,
        so its entry is relabelled, and so is any change to its entries. A
        withdrawal is a revision whatever the lease says: a session that earned
        before, ignoring the lease, and no longer does -- or that lost entries --
        may still be on the Display, which only a lapse-blind mark can correct.
        """
        if self._withdrawn_by(after):
            return "revised"
        if not after.holds():
            return "unchanged"
        if not self.holds():
            return "gained"
        same = (
            self._declared() == after._declared()
            and self._entries() == after._entries()
        )
        return "unchanged" if same else "revised"

    def _withdrawn_by(self, after: MenuListing) -> bool:
        """Whether ``after`` takes away something the Display may be showing."""
        if self._earned() and not after._earned():
            return True
        return not after.holds() and (
            self.holds() or self._entries() != after._entries()
        )

    def _declared(self) -> ClientIdentity | None:
        """The identity the listed session declared; ``None`` for no session."""
        return self._session.identity if self._session is not None else None

    def _entries(self) -> tuple[SessionCallback, ...]:
        """The entries the session registered -- a change to them is a revision.

        Read here, once, so every write that can add, withdraw or relabel an entry
        is a revision without restating the rule at the write.
        """
        return self._session.callbacks if self._session is not None else ()
