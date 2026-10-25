"""BatchSender -- pushes one drained batch to the display, and what it was sending.

The replicator's worker drains a batch and hands it here. A send that fails raises
out of :meth:`BatchSender.push` as a :class:`BatchSendError` that carries what the
failure should be charged to: the scenes that were in flight and the dial they went
out on. What a push has put at risk so far is one :class:`_InFlight`, made for the
push and gone with it, so a stale value from an earlier push cannot exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import CrashAttribution
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.frame_owner_facts import FrameOwnerFactsReader
    from punt_lux.domain.hub.replicator_ports import (
        CallbackMenuReader,
        ClientProvider,
        DisplaySender,
        MenuReader,
        WriteSeatPort,
    )
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.ids import SceneId

__all__ = ["BatchSendError", "BatchSender"]

# The isolation-mode roundtrip budget: after each singleton send, wait this
# long for the display to ack a ping -- long enough under load, short enough
# that a wedged display trips recovery quickly and blames the real crasher.
_PROBE_TIMEOUT_SECONDS = 1.0


@dataclass(eq=False)  # an exception cannot be frozen: it gets a traceback attached
class BatchSendError(Exception):
    """A send of the batch failed: why, what was in flight, and the dial it used."""

    cause: OSError  # the socket failure: a wedged display, a dead peer, a Hub retire
    suspect: frozenset[SceneId]  # the scenes in flight when the send failed
    dial: DialRef | None  # the dial the send went out on; None if none was had

    def __str__(self) -> str:
        return str(self.cause)


@final
class _InFlight:
    """What one push has put at risk so far: the scenes in flight and the dial."""

    _suspect: frozenset[SceneId]
    _dial: DialRef | None
    __slots__ = ("_dial", "_suspect")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._suspect = frozenset()
        self._dial = None
        return self

    def risking(self, scenes: frozenset[SceneId]) -> None:
        """Record the scenes the next send that can raise puts in flight."""
        self._suspect = scenes

    def on(self, dial: DialRef) -> None:
        """Record the dial the next send goes out on."""
        self._dial = dial

    def failed(self, cause: OSError) -> BatchSendError:
        """The error that charges ``cause`` to what is in flight now."""
        return BatchSendError(cause, self._suspect, self._dial)


@final
class BatchSender:
    """Sends a batch's menus and scenes, raising what a failure should blame."""

    _reader: SceneReader
    _menu_reader: MenuReader
    _callback_reader: CallbackMenuReader
    _clients: ClientProvider
    _seat: WriteSeatPort
    _attribution: CrashAttribution
    _owner_facts: FrameOwnerFactsReader
    __slots__ = (
        "_attribution",
        "_callback_reader",
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
        self._owner_facts = owner_facts
        return self

    def push(self, batch: DrainedBatch) -> tuple[SceneId, ...]:
        """Send the batch and return the scenes it found empty, for later reclaim.

        A socket failure raises :class:`BatchSendError` carrying the failure, the
        scenes in flight and the dial; anything that is not one passes through.

        Quarantined scenes are filtered before either send path runs (Invariant
        1: a quarantined scene is never replicated), enforced here regardless
        of what queued it. A menu send is attributed to the *empty* suspect
        set: a menu-caused crash is not a scene-caused one, so blaming the
        whole batch would reintroduce isolation's false-positive class — the
        empty suspect still trips isolation, so later scene sends are singles.
        """
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
            flight.risking(frozenset())
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
        """Send every scene as one coalesced batch — the suspect set on a death.

        A send failure anywhere aborts the whole method, so the suspect is set
        once, to the whole batch: a socket-level failure can't tell which of
        several already-accepted sends actually crashed the Display.
        """
        flight.risking(scenes)
        # Each ``_send_scene`` sends and reports whether the scene was empty; the
        # comprehension keeps the empties as reclaim candidates.
        return tuple(scene for scene in scenes if self._send_scene(scene, flight))

    def _isolating(
        self, scenes: frozenset[SceneId], flight: _InFlight
    ) -> tuple[SceneId, ...]:
        """Send every scene alone, with a liveness probe between sends.

        The suspect narrows to the singleton before each send, and a synchronous
        ``confirm_alive`` runs *after* each send, *before* the next — without it,
        scene N's crash surfaces only as a broken pipe on the *next* write,
        attributing to innocent N+1. The probe forces the crash to surface while
        the suspect is still {N}, and it waits for the display's own pong: a busy
        dial proves nothing about scene N. A failed probe raises OSError, which
        the replicator hands to recovery.
        """
        emptied: list[SceneId] = []
        for scene_id in scenes:
            flight.risking(frozenset({scene_id}))
            if self._send_scene(scene_id, flight):
                emptied.append(scene_id)
            probe = self._clients.get().desk.asks()  # connects if the dial is gone
            flight.on(probe.dial)
            if not probe.confirm_alive(_PROBE_TIMEOUT_SECONDS):
                msg = f"display did not ack probe after sending {scene_id!r}"
                raise OSError(msg)
        return tuple(emptied)

    def _sender(self, flight: _InFlight) -> DisplaySender:
        """A sender pinned to the dial that is current, noting it for a failure."""
        self._clients.get()  # connects if the dial is gone
        sender = self._seat.current()
        flight.on(sender.dial)
        return sender

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
