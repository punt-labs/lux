"""BeadsSource — where a board's rows come from, and what it raises when it cannot.

``BeadsBrowser`` is the one that runs in a session, reading the repository's
issues from the session's own shell. The applet asks only for the contract, so
what stands in for ``bd`` in a test is a class with a ``load`` method and nothing
else to satisfy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.apps.beads_load import BeadsLoad

__all__ = ["BeadsSource", "BoardUnavailableError"]


class BeadsSource(Protocol):
    """The one thing a board needs of its issues: a run that reads them."""

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        """Return the completed run: what it read, and where its time went."""
        ...


class BoardUnavailableError(Exception):
    """The issues could not be read, worded for the user rather than for the log.

    It carries the sentence a user should see, because the two callers that catch
    it do opposite things with it — one renders it where the board would have
    been, the other logs it and leaves the board it already had standing.
    """
