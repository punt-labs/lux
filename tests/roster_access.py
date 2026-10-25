"""Test-only access to a roster's release, which production hands away once."""

from __future__ import annotations

from punt_lux.domain.hub.client_roster import ClientRoster, RosterRelease

__all__ = ["release_of"]


def release_of(roster: ClientRoster) -> RosterRelease:
    """A release that asks ``roster`` itself, without taking the roster's one."""
    return RosterRelease(roster._release_departed)  # test seam
