"""Ports the Hub replicator depends on — the display connection and its lifecycle.

The replicator is the sole writer to the display, but it does not own the
socket or the process. It reaches them through structural ports so the
concurrency logic is tested against fakes, not a live socket: ``DisplaySender``
(the fire-and-forget send surface, pinned to one dial), ``WriteSeatPort`` (where
senders are made), ``DisplayProbe`` (the isolation loop's ping, pinned to one
dial), ``ClientProvider`` (connects, hands out the seat and the death queue once,
drops a dead dial, waits), ``DisplayLifecycle`` (kills a wedged display; its service
unit respawns it), and ``DirtyMarker`` (the queue-only side a fresh-connect hook marks
after declaring its manifest, DES-068).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from punt_lux.domain.hub.disconnected_retry import ReconnectWaiter
from punt_lux.domain.hub.scene_presentation import ScenePusher

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.dial_death import DialDeath
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.ids import SceneId

__all__ = [
    "CallbackMenuReader",
    "ClientProvider",
    "DeathQueuePort",
    "DirtyMarker",
    "DisplayLifecycle",
    "DisplayProbe",
    "DisplaySender",
    "MenuReader",
    "WriteSeatPort",
]


@runtime_checkable
class CallbackMenuReader(Protocol):
    """The live ``Clients`` menu, read fresh at send time.

    Composed from the session registry, so whatever sessions are in lease when
    the send runs is what the display renders -- the same read-at-send
    discipline the agent bar uses, with no payload to go stale."""

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

    Extends ``ScenePusher`` (``send_scene``) with the two menu writes so the
    replicator is the sole writer of the menu state: ``set_menu`` for the agent
    menu bar and ``set_callback_menus`` for the ``Clients`` menu. It is pinned to
    one dial, which a failed send names to drop.
    """

    @property
    def dial(self) -> DialRef:
        """The dial every send goes out on: what a failed send names to drop."""
        ...

    def set_menu(self, menus: list[dict[str, object]]) -> None:
        """Replace the display's agent menu bar with the given wire menus."""

    def set_callback_menus(self, submenus: list[dict[str, object]]) -> None:
        """Replace the display's Clients menu."""


@runtime_checkable
class WriteSeatPort(Protocol):
    """Where senders are made: the replicator's one way to write to the display."""

    def current(self) -> DisplaySender:
        """A sender pinned to the dial that is current now."""
        ...


@runtime_checkable
class DisplayProbe(Protocol):
    """The isolation loop's ping of the display, pinned to one dial."""

    @property
    def dial(self) -> DialRef:
        """The dial the probe goes out on: what a failed probe names to drop."""
        ...

    def await_acks(self, timeout: float) -> bool:
        """Wait for the display to ack every scene written to this dial.

        The synchronous check between consecutive singleton sends: it makes the
        display take scene N (ack it after a swap, or die holding it) before N+1 goes
        out, so a death leaves a ledger of one scene. A pong would say only that the
        display is reading. ``False``: no ack came in time. Raising OSError is a
        failure of the dial, and the caller propagates it.
        """
        ...


@runtime_checkable
class DeathQueuePort(Protocol):
    """The deaths dials left and nobody has charged: the charger's alone."""

    def take(self) -> DialDeath | None:
        """The oldest death, handed over once."""
        ...

    def put_back(self, death: DialDeath) -> None:
        """Return a death whose charge failed: it is the next one taken."""


@runtime_checkable
class ClientProvider(ReconnectWaiter, Protocol):
    """Connects the display, hands out its write seat once, drops a dead dial, waits."""

    def asks(self) -> DisplayProbe:
        """Connect if the dial is gone, and return a probe pinned to the dial in use.

        Raises ``DisplayNotConnectedError`` if no display can be reached.
        """
        ...

    def take_writer(self) -> WriteSeatPort:
        """Hand over the seat senders are made at; asked once, by the one writer."""
        ...

    def drop(self, dial: DialRef) -> None:
        """Retire ``dial`` if still current, so the next ``asks`` binds afresh."""

    def drop_unresponsive(self, dial: DialRef) -> None:
        """Retire ``dial``, open but silent, as the display's end; charge its ledger."""

    def take_deaths(self) -> DeathQueuePort:
        """Hand over the queue of display deaths; asked once, by the one charger."""
        ...

    def request_stop(self) -> None:
        """Wake a parked ``wait_for_reconnect`` past the disconnected backoff."""


@runtime_checkable
class DisplayLifecycle(Protocol):
    """Kills a wedged display; its own service unit respawns it.

    The Hub used to both reap and respawn — a second supervisor racing the
    launchd/systemd unit that now owns respawn. Its remaining role is killing.
    """

    def reap(self, timeout: float = ...) -> None:
        """Terminate the socket's current owner, by its peer credential."""


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
