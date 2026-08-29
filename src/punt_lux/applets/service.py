"""AppletService — what an applet must be able to do to own a menu entry.

The contract has three phases and they are separated by their deadlines, which
is the whole reason a menu entry feels like a menu entry:

- ``prefetch`` runs before anyone clicks and has no deadline at all;
- ``acknowledge`` is what the user sees happen, inside a budget measured in
  milliseconds;
- ``service`` is whatever the entry actually does, and may take as long as it
  takes because something is already on screen.

An applet satisfies this by having the methods, not by inheriting anything: the
leg holds whatever it was handed and calls it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.latency import ClickLatency

__all__ = ["AppletService"]


@runtime_checkable
class AppletService(Protocol):
    """One callback a session owns: the entry it puts up and the work a click does."""

    @property
    def callback_id(self) -> str:
        """The id a click on this entry carries back to the session."""
        ...

    @property
    def label(self) -> str:
        """The entry the display shows under this session's submenu."""
        ...

    def prefetch(self) -> None:
        """Do now what a click would otherwise wait for, so the first one does not.

        Run once the entry is registered, off the loop and off any click. It
        renders nothing and reports nothing to the user: a failure means only
        that the first click pays the wait, which is what it did before there was
        a prefetch at all.
        """
        ...

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """Show the user their click landed — the fastest visible thing there is.

        The clock is passed rather than only wrapped around the call because what
        the answer *was* belongs on the line beside how long it took: a click
        answered with a board already loaded is a different click from one
        answered with a placeholder.
        """
        ...

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        """Do the work a click asks for, pushing whatever it produces via ``client``.

        The stages of that work are timed into ``latency`` and reported with the
        answer, because a click that was answered in 97 ms and produced a board
        two seconds later is a different problem from either number alone.
        """
        ...
