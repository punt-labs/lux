"""HubReplicator — the one background worker that writes to the display.

Every MCP mutation tool and every Hub-side click writes only to ``HubDisplay``
and marks the changed scene dirty; this worker alone sends those changes to
the display and handles a slow or dead one, so a stuck display never freezes an agent.

The worker waits on a ``DirtySignal``, wakes when a scene is dirty or the menu
changed, coalesces a 16 ms burst, and drains the whole changed set. It repaints
each scene from a copy taken under the store's read lock, so the store lock and
client send lock are never held together; an emptied scene is pushed with no
roots to blank its own frame. A send is time-limited (``SO_SNDTIMEO``): a wedged
display raises ``BlockingIOError``, a dead peer raises ``OSError``, both handed
to ``SendRecovery``. A third condition, no display connected at all
(``DisplayNotConnectedError``), paces its own slower backoff (§6).

The send loop also hosts the crash-loop quarantine (display-crash-quarantine.md):
normal replication is *batching* — every drained scene is sent, and a death
anywhere is attributed to the whole batch, since a socket-level failure can't
tell which render actually crashed. The first attributed death switches to
*isolation*: each live, non-quarantined scene sends alone, for a single
suspect, left only once ``CrashAttribution`` sees a death-free
``STABLE_INTERVAL``; a scene at the threshold is quarantined and excluded
from every future send, breaking the respawn loop."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.backoff_config import BackoffConfig
from punt_lux.domain.hub.crash_attribution import CrashAttribution
from punt_lux.domain.hub.dirty_signal import DirtySignal
from punt_lux.domain.hub.disconnected_retry import DisconnectedRetry
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import QuarantinePort
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.replicator_ports import (
        CallbackMenuReader,
        ClientProvider,
        DisplayLifecycle,
        MenuReader,
    )
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.ids import SceneId

logger = logging.getLogger(__name__)

# One frame at 60 fps: after a wake, wait this long so a burst of update() calls
# coalesces into a single resend.
_COALESCE_SECONDS = 0.016
# Bound the join at shutdown so a wedged final flush cannot hang the process.
_STOP_JOIN_TIMEOUT = 5.0
# After a recovery that could not heal the display, wait this long before the
# first retry so the worker never spins. Doubles each failure up to the cap
# and resets on a clean cycle, so a display that stays wedged retries sanely.
_BASE_BACKOFF_SECONDS = 0.1
_MAX_BACKOFF_SECONDS = 2.0
# The disconnected-display retry: no display has ever connected, which can
# last indefinitely, so this paces slower than the wedged backoff above.
_DISCONNECTED_BASE_DELAY_SECONDS = 2.0
_DISCONNECTED_MAX_DELAY_SECONDS = 120.0
# The isolation-mode roundtrip budget: after each singleton send, wait this
# long for the display to ack a ping — long enough under load, short enough
# that a wedged display trips recovery quickly and blames the real crasher.
_PROBE_TIMEOUT_SECONDS = 1.0
# The idle-tick period between wakeups with no write, so stability checks
# still fire in a quiet system that would otherwise never wake the worker.
_STABILITY_TICK_SECONDS = 1.0


@final
@dataclass(frozen=True, slots=True)
class _CycleOutcome:
    """One push cycle's result — exactly one of three distinct causes.

    ``clean``: a real send succeeded; ``emptied`` names scenes to reclaim.
    ``recovered``: a send failed while CONNECTED and was healed -- the wedged
    backoff advances. ``disconnected``: never connected at all -- the
    disconnected backoff advances instead; mutually exclusive by construction.
    """

    outcome: Literal["clean", "recovered", "disconnected"]
    emptied: tuple[SceneId, ...] = ()


@final
class HubReplicator:
    """The single background writer to the display connection.

    Composes the store's scene reader (its locked read side), the client
    provider, the dirty signal, and the ``SendRecovery`` that heals a failed
    send. ``mark_dirty``/``mark_menus`` are what surface tools call; this
    worker thread owns every send."""

    _reader: SceneReader
    _menu_reader: MenuReader
    _callback_reader: CallbackMenuReader
    _clients: ClientProvider
    _signal: DirtySignal
    _recovery: SendRecovery
    _attribution: CrashAttribution
    _thread: threading.Thread | None
    _backoff: float
    _current_suspect: frozenset[SceneId]
    _disconnected_retry: DisconnectedRetry
    __slots__ = (
        "_attribution",
        "_backoff",
        "_callback_reader",
        "_clients",
        "_current_suspect",
        "_disconnected_retry",
        "_menu_reader",
        "_reader",
        "_recovery",
        "_signal",
        "_thread",
    )

    def __new__(
        cls,
        reader: SceneReader,
        menu_reader: MenuReader,
        callback_reader: CallbackMenuReader,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
        quarantine: QuarantinePort,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
        self._menu_reader = menu_reader
        self._callback_reader = callback_reader
        self._clients = clients
        self._signal = DirtySignal()
        self._attribution = CrashAttribution(quarantine)
        # Wire the tally reset to the quarantine-clear cascade so a fixed
        # scene needs the full ATTRIBUTION_THRESHOLD again, not one fresh
        # death against a lingering in-window tally.
        quarantine.add_quarantine_cleared_observer(self._attribution.clear_tally)
        self._recovery = SendRecovery(
            clients, lifecycle, self._signal, self._attribution, RespawnBackoff()
        )
        self._thread = None
        self._backoff = _BASE_BACKOFF_SECONDS
        self._current_suspect = frozenset()
        # A second, independently-tuned pacer for the never-connected case.
        self._disconnected_retry = DisconnectedRetry(
            BackoffConfig(
                base_delay=_DISCONNECTED_BASE_DELAY_SECONDS,
                max_delay=_DISCONNECTED_MAX_DELAY_SECONDS,
            )
        )
        return self

    # -- surface API: queue-only, called by tools and click dispatch --------

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Signal that ``scene_id`` changed. Queue-only — never sends."""
        self._signal.mark_dirty(scene_id)

    def mark_menus(self) -> None:
        """Signal that the menu registry changed. Queue-only — never sends.

        Payload-less: the operation writes the Hub registry and flags it here;
        this worker alone reads the registry fresh and sends it.
        """
        self._signal.mark_menus()

    # -- lifecycle: starts with luxd, stops with luxd -----------------------

    def start(self) -> None:
        """Start the worker thread. Idempotent; raises if already stopped."""
        self._require_live()
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="lux-replicator", daemon=True
        )
        self._thread.start()

    def _require_live(self) -> None:
        """Reject a restart after a stop — a stopped replicator is terminal.

        The stop latches the dirty signal shutting, so a fresh thread would
        exit at once and every mark would silently go nowhere; ``start`` and
        the worker's own exit read the same signal, so they can never disagree.
        """
        if self._signal.is_shutting:
            msg = "replicator was stopped; construct a fresh one to restart"
            raise RuntimeError(msg)

    def stop(self) -> None:
        """Flush pending, stop, and join. A stop is terminal, even before a
        start: latches the dirty signal shutting so a later ``start`` raises,
        wakes a parked disconnected wait so the join below isn't trapped
        behind it, and is a no-op (nothing to join) before any ``start``.
        """
        self._signal.request_stop()
        self._clients.request_stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=_STOP_JOIN_TIMEOUT)
            if thread.is_alive():
                logger.warning("replicator worker did not stop within timeout")
            else:
                self._thread = None

    # -- worker loop --------------------------------------------------------

    def _run(self) -> None:
        """Drain-and-push until asked to stop, surviving any single-cycle error.

        Stability checks fire once per iteration, work or no work, so a quiet
        system with no further write still exits isolation once
        ``STABLE_INTERVAL`` elapses — time-driven, not gated on the next
        write. The idle-tick wake bounds the wait so the check runs on time.
        """
        while True:
            batch = self._signal.wait_and_drain(
                _COALESCE_SECONDS, idle_tick_seconds=_STABILITY_TICK_SECONDS
            )
            if batch.has_work:
                self._run_cycle(batch)
            self._tick_stability()
            if batch.shutting:
                return

    def _tick_stability(self) -> None:
        """Run the two death-free-interval checks that decay per-episode state."""
        self._attribution.exit_isolation_if_stable()
        self._recovery.reset_backoff_if_stable()

    def _run_cycle(self, batch: DrainedBatch) -> None:
        """Push the batch; reclaim only on a genuinely clean cycle, else back off.

        Three outcomes (``_CycleOutcome``): ``disconnected`` does nothing
        further — already restored and waited, so this never advances the
        wedged-display delay for a cycle that never wedged anything.
        ``recovered`` still counts as a failure, so that delay grows. A
        genuinely ``clean`` cycle resets both backoffs and reclaims what it
        emptied — deferred here so a later failure can't strand a reclaim.
        """
        try:
            result = self._push_cycle(batch)
        except Exception:
            if batch.shutting:
                logger.exception("replicator shutdown flush failed; dropping the batch")
                return
            logger.exception("replicator cycle failed; retrying the batch")
            self._recover_from_exception(batch)
            return
        if result.outcome == "disconnected":
            return  # _push_cycle restored the batch (waited, unless shutting)
        if result.outcome == "recovered":
            if not batch.shutting:
                self._back_off()
            return
        self._backoff = _BASE_BACKOFF_SECONDS
        self._disconnected_retry.reset()
        self._reclaim_emptied(result.emptied)

    def _recover_from_exception(self, batch: DrainedBatch) -> None:
        """Restore the batch and back off after a non-socket cycle failure."""
        self._recovery.restore(batch)
        self._back_off()

    def _push_cycle(self, batch: DrainedBatch) -> _CycleOutcome:
        """Send the cycle; heal a bounded send failure, else report the clean result.

        ``DisplayNotConnectedError`` means no display was ever connected, so
        it paces the disconnected backoff, not the wedged one -- every OTHER
        ``RuntimeError`` (a mid-send teardown, a listener-thread guard) is NOT
        this condition and propagates to the caller's outer guard instead.
        ``BlockingIOError`` (send timeout) is a wedged display, reaped and
        respawned; ``OSError`` (dead peer) only reconnects -- either way the
        death is attributed to ``_current_suspect``, set by ``_attempt``
        immediately before each send that can raise."""
        since_gen = self._clients.reconnect_generation  # BEFORE the attempt: race-safe
        try:
            emptied = self._attempt(batch)
        except DisplayNotConnectedError:
            self._recovery.restore(batch)
            if not batch.shutting:
                self._disconnected_retry.wait(self._clients, since_gen=since_gen)
            return _CycleOutcome(outcome="disconnected")
        except BlockingIOError as exc:
            self._recovery.recover(
                batch,
                wedged=True,
                suspect=self._current_suspect,
                render_error=str(exc),
            )
            return _CycleOutcome(outcome="recovered")
        except OSError as exc:
            self._recovery.recover(
                batch,
                wedged=False,
                suspect=self._current_suspect,
                render_error=str(exc),
            )
            return _CycleOutcome(outcome="recovered")
        return _CycleOutcome(outcome="clean", emptied=emptied)

    def _back_off(self) -> None:
        """Sleep the current retry delay, then grow it toward the cap."""
        time.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)

    @property
    def disconnected_delay(self) -> float:
        """Return the current not-connected retry delay, in seconds (design §9)."""
        return self._disconnected_retry.current_delay

    def _attempt(self, batch: DrainedBatch) -> tuple[SceneId, ...]:
        """Send the cycle and return the scenes it found empty, for later reclaim.

        Quarantined scenes are filtered before either send path runs (Invariant
        1: a quarantined scene is never replicated), enforced here regardless
        of what queued it. A menu send is attributed to the *empty* suspect
        set: a menu-caused crash is not a scene-caused one, so blaming the
        whole batch would reintroduce isolation's false-positive class — the
        empty suspect still trips isolation, so later scene sends are singles.
        """
        scenes = frozenset(
            s for s in batch.scenes if not self._attribution.is_quarantined(s)
        )
        if batch.menus_dirty:
            self._current_suspect = frozenset()
            # Read the agent bar and the live sessions fresh, so the newest menu
            # state wins even if a change landed after this batch was drained.
            bar = self._menu_reader.wire_snapshot()
            callback_menus = self._callback_reader.callback_menu_wire()
            sender = self._clients.get()
            sender.set_menu([dict(menu) for menu in bar])
            sender.set_callback_menus(callback_menus)
        if self._attribution.mode == "isolating":
            return self._attempt_isolating(scenes)
        return self._attempt_batching(scenes)

    def _attempt_batching(self, scenes: frozenset[SceneId]) -> tuple[SceneId, ...]:
        """Send every scene as one coalesced batch — the suspect set on a death.

        A send failure anywhere aborts the whole method, so ``_current_suspect``
        is set once, to the whole batch: a socket-level failure can't tell which
        of several already-accepted sends actually crashed the Display.
        """
        self._current_suspect = scenes
        # Each ``_send_scene`` sends and reports whether the scene was empty; the
        # comprehension keeps the empties as reclaim candidates.
        return tuple(scene for scene in scenes if self._send_scene(scene))

    def _attempt_isolating(self, scenes: frozenset[SceneId]) -> tuple[SceneId, ...]:
        """Send every scene alone, with a liveness probe between sends.

        ``_current_suspect`` narrows to the singleton before each send, and a
        synchronous ``probe_alive`` runs *after* each send, *before* the next —
        without it, scene N's crash surfaces only as a broken pipe on the
        *next* write, attributing to innocent N+1. The probe forces the crash
        to surface while the suspect is still {N}. A failed probe raises
        OSError, caught by ``_push_cycle`` and handed to recovery.
        """
        emptied: list[SceneId] = []
        for scene_id in scenes:
            self._current_suspect = frozenset({scene_id})
            if self._send_scene(scene_id):
                emptied.append(scene_id)
            if not self._clients.get().probe_alive(_PROBE_TIMEOUT_SECONDS):
                msg = f"display did not ack probe after sending {scene_id!r}"
                raise OSError(msg)
        return tuple(emptied)

    def _send_scene(self, scene_id: SceneId) -> bool:
        """Send a copy of the scene; return whether it was empty (a reclaim candidate).

        The store returns a snapshot whose roots are already copied out, so the
        send runs with no store lock held. An empty scene blanks its own frame.
        """
        snapshot = self._reader.snapshot(scene_id)
        snapshot.push(self._clients.get())
        return snapshot.is_empty

    def _reclaim_emptied(self, scenes: tuple[SceneId, ...]) -> None:
        """Forget each blanked scene's frame, re-checked rootless under the lock.

        Deferred to a clean cycle so a failed send never reclaims a scene the
        recovery must retry. The rootless re-check keeps a re-show that landed
        during the send window: it installed roots and a new frame, so the
        scene is no longer rootless and that new frame is kept.
        """
        for scene_id in scenes:
            self._reader.reclaim_if_rootless(scene_id)
