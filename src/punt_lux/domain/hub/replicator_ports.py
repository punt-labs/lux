"""Ports the Hub replicator depends on — the display connection and its lifecycle.

The replicator is the sole writer to the display, but it does not own the socket
or the process. It reaches them through three structural ports so the concurrency
logic is tested against fakes, not a live socket:

- ``DisplaySender`` — the fire-and-forget send surface (a ``DisplayLink``).
- ``ClientProvider`` — hands out the current sender and drops a dead one so the
  next hand-out reconnects (the Hub's ``ClientRegistry``).
- ``DisplayLifecycle`` — kills a wedged display and starts a fresh one
  (``DisplayPaths``).
- ``DirtyMarker`` — the queue-only side of the replicator (``HubReplicator``)
  that a fresh-connect hook marks after declaring its manifest (DES-068).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from punt_lux.domain.hub.scene_presentation import ScenePusher

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from punt_lux.domain.ids import SceneId

__all__ = [
    "CallbackMenuReader",
    "ClientProvider",
    "DirtyMarker",
    "DisplayLifecycle",
    "DisplaySender",
    "MenuReader",
]


@runtime_checkable
class CallbackMenuReader(Protocol):
    """The live ``Clients`` menu, read fresh at send time.

    Composed from the session registry, so whatever sessions are in lease when the
    send runs is what the display renders — the same read-at-send discipline the
    agent bar uses, with no payload to go stale.
    """

    def callback_menu_wire(self) -> list[dict[str, object]]:
        """Return the uniform ``Clients`` menu as wire payloads."""
        ...


@runtime_checkable
class MenuReader(Protocol):
    """The registry's read side for the replicator — a consistent wire snapshot.

    The worker reads this fresh at send time, so whatever the registry holds when
    the send runs is what the display receives; a stale payload can never be
    resent because there is no payload to go stale.
    """

    def wire_snapshot(self) -> tuple[Mapping[str, object], ...]:
        """Return the agent menu bar as wire payloads, read atomically."""
        ...


@runtime_checkable
class DisplaySender(ScenePusher, Protocol):
    """A connection the replicator sends whole scenes and menus over.

    Extends ``ScenePusher`` (``show_async``) with the two menu writes so the
    replicator is the sole writer of the menu state: ``set_menu`` for the agent
    menu bar and ``set_callback_menus`` for the ``Clients`` menu.
    """

    def set_menu(self, menus: list[dict[str, object]]) -> None:
        """Replace the display's agent menu bar with the given wire menus."""

    def set_callback_menus(self, submenus: list[dict[str, object]]) -> None:
        """Replace the display's Clients menu."""

    def probe_alive(self, timeout: float) -> bool:
        """Return whether the display responded to a ping within ``timeout``.

        Used by ``HubReplicator``'s isolation-mode loop as a synchronous
        liveness check between consecutive singleton probes: a scene N whose
        render crashed the display surfaces as a broken pipe on the *next*
        write, so without a roundtrip in between, the death would attribute
        to scene N+1 (which was in flight when the write raised) rather than
        to scene N (the real culprit). Raising OSError/BlockingIOError is
        also a "no" — the caller propagates either as a failure of the last
        scene sent.
        """
        ...


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


@runtime_checkable
class DirtyMarker(Protocol):
    """Marks scenes and the menu dirty on the replicator, queue-only.

    ``ClientRegistry``'s connect-success hook (DES-068) marks through this
    port after declaring a fresh connection's manifest, so the display's
    content catches up to what the manifest just told it the Hub holds.
    """

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Signal that ``scene_id`` changed. Queue-only — never sends."""

    def mark_menus(self) -> None:
        """Signal that the menu registry changed. Queue-only — never sends."""
