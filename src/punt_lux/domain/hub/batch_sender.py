"""BatchSender -- pushes one drained batch to the display, and what it was sending.

The replicator's worker drains a batch and hands it here. A send that fails raises
out of :meth:`BatchSender.push` as a :class:`BatchSendError` that carries the socket
failure and the dial the send went out on. Who is to blame for a display's death is not
read from the circumstances of the failed send: it is the dial's own ledger, charged by
:class:`~punt_lux.domain.hub.death_charger.DeathCharger` at the start of every push and
again by recovery, whoever found the dial dead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.death_charger import DeathCharger

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import CrashAttribution
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.frame_owner_facts import FrameOwnerFactsReader
    from punt_lux.domain.hub.replicator_ports import (
        CallbackMenuReader,
        ClientProvider,
        DisplayProbe,
        DisplaySender,
        MenuReader,
        WriteSeatPort,
    )
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.ids import SceneId

__all__ = ["BatchSendError", "BatchSender"]

# The isolation-mode roundtrip budget: after each singleton send, wait this
# long for the display to ack the scene -- long enough under load, short enough
# that a wedged display trips recovery quickly and blames the real crasher.
_PROBE_TIMEOUT_SECONDS = 1.0


@dataclass(eq=False)  # an exception cannot be frozen: it gets a traceback attached
class BatchSendError(Exception):
    """A send of the batch failed: why, and the dial it went out on."""

    cause: OSError  # the socket failure: a wedged display, a dead peer, a Hub retire
    dial: DialRef | None  # the dial the send went out on; None if none was had

    def __str__(self) -> str:
        return str(self.cause)


@final
class _InFlight:
    """The dial one push has used so far: what a failure names for the drop."""

    _dial: DialRef | None
    __slots__ = ("_dial",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._dial = None
        return self

    def on(self, dial: DialRef) -> None:
        """Record the dial the next send goes out on."""
        self._dial = dial

    def failed(self, cause: OSError) -> BatchSendError:
        """The error that names ``cause`` and the dial in use now."""
        return BatchSendError(cause, self._dial)


@final
class BatchSender:
    """Sends a batch's menus and scenes, raising what a failure should drop."""

    _reader: SceneReader
    _menu_reader: MenuReader
    _callback_reader: CallbackMenuReader
    _clients: ClientProvider
    _seat: WriteSeatPort
    _attribution: CrashAttribution
    _charger: DeathCharger
    _owner_facts: FrameOwnerFactsReader
    __slots__ = (
        "_attribution",
        "_callback_reader",
        "_charger",
        "_clients",
        "_menu_reader",
        "_owner_facts",
        "_reader",
        "_seat",
    )

    def __new__(
        cls,
        reader: SceneReader,
        menu_reader: MenuReader,
        callback_reader: CallbackMenuReader,
        clients: ClientProvider,
        writes: WriteSeatPort,
        attribution: CrashAttribution,
        owner_facts: FrameOwnerFactsReader,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
        self._menu_reader = menu_reader
        self._callback_reader = callback_reader
        self._clients = clients
        self._seat = writes
        self._attribution = attribution
        self._charger = DeathCharger(clients, attribution)
        self._owner_facts = owner_facts
        return self

    def charge_deaths(self) -> None:
        """Charge every death on record, once; the idle replicator's look."""
        self._charger.charge()

    def reclaim_emptied(self, scenes: tuple[SceneId, ...]) -> None:
        """Forget each blanked scene's frame, re-checked rootless under the lock.

        Deferred to a clean cycle so a failed send never reclaims a scene the
        recovery must retry. The rootless re-check keeps a re-show that landed
        during the send window: it installed roots and a new frame, so the
        scene is no longer rootless and that new frame is kept.
        """
        for scene_id in scenes:
            self._reader.reclaim_if_rootless(scene_id)

    def push(self, batch: DrainedBatch) -> tuple[SceneId, ...]:
        """Send the batch; report the scenes found empty, the reclaim candidates.

        Deaths already on record are charged first, so a scene they take to the
        threshold is quarantined before the batch is filtered. A socket failure
        raises :class:`BatchSendError` carrying the failure and the dial; anything
        that is not one passes through.

        Quarantined scenes are filtered before either send path runs (Invariant
        1: a quarantined scene is never replicated), enforced here regardless
        of what queued it.
        """
        self._charger.charge()
        flight = _InFlight()
        try:
            return self._push(batch, flight)
        except OSError as exc:
            raise flight.failed(exc) from exc

    def _push(self, batch: DrainedBatch, flight: _InFlight) -> tuple[SceneId, ...]:
        scenes = frozenset(
            s for s in batch.scenes if not self._attribution.is_quarantined(s)
        )
        if batch.menus_dirty:
            # Read the agent bar and the live sessions fresh, so the newest menu
            # state wins even if a change landed after this batch was drained.
            bar = self._menu_reader.wire_snapshot()
            callback_menus = self._callback_reader.callback_menu_wire()
            sender = self._sender(flight)
            sender.set_menu([dict(menu) for menu in bar])
            sender.set_callback_menus(callback_menus)
        if self._attribution.mode == "isolating":
            return self._isolating(scenes, flight)
        return self._batching(scenes, flight)

    def _batching(
        self, scenes: frozenset[SceneId], flight: _InFlight
    ) -> tuple[SceneId, ...]:
        """Send every scene as one coalesced batch.

        Each ``_send_scene`` sends and reports whether the scene was empty; the
        comprehension keeps the empties as reclaim candidates.
        """
        return tuple(scene for scene in scenes if self._send_scene(scene, flight))

    def _isolating(
        self, scenes: frozenset[SceneId], flight: _InFlight
    ) -> tuple[SceneId, ...]:
        """Send every scene alone, and wait for its ack before the next goes out.

        The ack is sent only after a swap that completed with the scene installed, so
        waiting for it makes the display take scene N (survive it, or die holding it)
        before N+1 goes out: a death leaves a ledger of one. A pong would say only
        that the display is reading. An ack that never comes is a display that stalled
        or died holding the scene, so the dial is given up as unresponsive: its ledger
        is charged and carried, and nothing more is sent on it.
        """
        emptied: list[SceneId] = []
        for scene_id in scenes:
            if self._send_scene(scene_id, flight):
                emptied.append(scene_id)
            probe = self._connected(flight)  # connects if the dial is gone
            flight.on(probe.dial)
            if not probe.await_acks(_PROBE_TIMEOUT_SECONDS):
                self._clients.drop_unresponsive(probe.dial)
                msg = f"display did not ack {scene_id!r} after a swap"
                raise ConnectionClosedError(msg)
        return tuple(emptied)

    def _sender(self, flight: _InFlight) -> DisplaySender:
        """A sender pinned to the dial that is current, noting it for a failure."""
        self._connected(flight)  # connects if the dial is gone
        sender = self._seat.current()
        flight.on(sender.dial)
        return sender

    def _connected(self, flight: _InFlight) -> DisplayProbe:
        """The ask port on the dial in use, connecting first if there is none."""
        probe = self._clients.asks()
        flight.on(probe.dial)
        return probe

    def _send_scene(self, scene_id: SceneId, flight: _InFlight) -> bool:
        """Send a copy of the scene; return whether it was empty (a reclaim candidate).

        The store returns a snapshot whose roots are already copied out, so the
        send runs with no store lock held. An empty scene blanks its own frame;
        owner facts resolve fresh here (like the menu bar) and ``None`` leaves
        the display's cached snapshot alone rather than blanking it.
        """
        snapshot = self._reader.snapshot(scene_id)
        snapshot.push(self._sender(flight), self._owner_facts)
        return snapshot.is_empty
