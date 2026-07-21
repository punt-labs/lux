"""Ports the Hub replicator depends on — the display connection and its lifecycle.

The replicator is the sole writer to the display, but it does not own the socket
or the process. It reaches them through three structural ports so the concurrency
logic is tested against fakes, not a live socket:

- ``DisplaySender`` — the fire-and-forget send surface (a ``DisplayClient``).
- ``ClientProvider`` — hands out the current sender and drops a dead one so the
  next hand-out reconnects (the Hub's ``ClientRegistry``).
- ``DisplayLifecycle`` — kills a wedged display and starts a fresh one
  (``DisplayPaths``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from punt_lux.domain.hub.scene_presentation import ScenePusher

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ClientProvider", "DisplayLifecycle", "DisplaySender"]


@runtime_checkable
class DisplaySender(ScenePusher, Protocol):
    """A connection the replicator sends whole scenes, clears, and menus over.

    Extends ``ScenePusher`` (``show_async``) with ``clear_async`` so the
    replicator blanks the display before it repaints a coalesced batch, and with
    ``set_menu`` so the replicator is the sole writer of the menu bar too.
    """

    def clear_async(self) -> None:
        """Blank the display without waiting for an acknowledgement."""

    def set_menu(self, menus: list[dict[str, object]]) -> None:
        """Replace the display's menu bar with the given wire menus."""


@runtime_checkable
class ClientProvider(Protocol):
    """Hands out the one display connection and drops a dead one."""

    def get(self) -> DisplaySender:
        """Return the connected sender, reconnecting if the last was dropped."""
        ...

    def drop(self) -> None:
        """Close the current connection so the next ``get`` binds a fresh one."""


@runtime_checkable
class DisplayLifecycle(Protocol):
    """Kills a wedged display and ensures a fresh one — the reap/respawn pair."""

    def reap(self, timeout: float = ...) -> None:
        """Terminate the socket's current owner, by its peer credential."""

    def ensure(self, timeout: float = ...) -> Path:
        """Start a fresh display if none is live; return the socket path."""
        ...
