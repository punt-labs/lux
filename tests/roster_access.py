"""Test-only access to a roster's release, which production hands away once."""

from __future__ import annotations

from punt_lux.domain.hub.client_roster import ClientRoster, RosterRelease

__all__ = ["release_of"]


def release_of(roster: ClientRoster) -> RosterRelease:
    """A release over ``roster``'s own state, without taking the roster's one."""
    return RosterRelease(roster, roster._names, roster._key_of)  # test seam
