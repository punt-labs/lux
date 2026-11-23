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
    from punt_lux.applets.menu_entry import MenuEntry

__all__ = ["AppletService"]


@runtime_checkable
class AppletService(Protocol):
    """One callback a session owns: the entry it puts up and the work a click does."""

    @property
    def entry(self) -> MenuEntry:
        """The menu entry this session registers, and whose clicks it services."""
        ...

    def prefetch(self) -> None:
        """Do now what a click would otherwise wait for, so the first one does not.

        Runs once the entry is registered, off any click; a failure means only
        that the first click pays the wait it always paid without a prefetch.
        """
        ...

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """Show the user their click landed — the fastest visible thing there is.

        The clock is passed rather than wrapped around the call because what
        the answer *was* belongs beside how long it took.
        """
        ...

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        """Do the work a click asks for, pushing whatever it produces via ``client``.

        The stages are timed into ``latency`` and reported with the answer,
        since a fast acknowledge and a slow push are different problems.
        """
        ...
