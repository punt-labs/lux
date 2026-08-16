"""HubReplicator — the one background worker that writes to the display.

Every MCP mutation tool and every Hub-side click writes only to ``HubDisplay``
and marks the changed scene dirty; this worker alone sends those changes to the
display, and it alone handles a slow or dead one. So a stuck display can never
freeze an agent.

The worker waits on a ``DirtySignal``, wakes when a scene is dirty or the menu
changed, coalesces a 16 ms burst, and drains the whole changed set. It repaints
each scene from a copy the store took under its read lock and handed out, so the
store lock and the client send lock are never held together; an emptied scene is
pushed with no roots to blank its own frame. A send is time-limited
(``SO_SNDTIMEO`` on the socket): a
wedged display raises ``BlockingIOError`` and a dead peer raises ``OSError``, and
either failure is handed to ``SendRecovery``, which heals the display and re-marks
the work. A recovery that cannot heal the display restores the batch and backs
off, so nothing drained is ever lost.

The send loop is also where the crash-loop quarantine lives
(display-crash-quarantine.md): normal replication is *batching* — every scene the
signal drained is sent, and a death anywhere is attributed to the whole batch,
since a socket-level send failure cannot tell which scene actually crashed the
renderer. The first attributed death switches the worker to *isolation*: it stops
coalescing and sends each live, non-quarantined scene alone, so a death has a
single suspect. Isolation is left only once
:class:`~punt_lux.domain.hub.crash_attribution.CrashAttribution` has seen a
death-free ``STABLE_INTERVAL`` — never on one clean pass — and a scene that
reaches the attribution threshold is quarantined and excluded from every future
send, which is what breaks the respawn loop.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.crash_attribution import CrashAttribution
from punt_lux.domain.hub.dirty_signal import DirtySignal
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
# After a recovery that could not heal the display (an unspawnable process, a
# refused reconnect), wait this long before the first retry so the worker never
# spins. The delay doubles each consecutive failure up to the cap and resets on a
# clean cycle, so a permanently absent display logs at a sane rate, not a firehose.
_BASE_BACKOFF_SECONDS = 0.1
_MAX_BACKOFF_SECONDS = 2.0
# The isolation-mode roundtrip budget: after each singleton scene send, wait
# this long for the display to ack a ping. Long enough for the display to
# process one scene under load; short enough that a wedged display trips the
# recovery quickly and blames the actual crasher, not the next scene in line.
_PROBE_TIMEOUT_SECONDS = 1.0
# The idle-tick period between wakeups when no scene or menu write arrives.
# Bounds the wait so stability checks (isolation-exit and respawn-backoff
# reset) fire even in a quiet system where no future write would otherwise
# wake the worker.
_STABILITY_TICK_SECONDS = 1.0


@final
@dataclass(frozen=True, slots=True)
class _CycleOutcome:
    """The result of one push cycle: whether recovery ran, and the empties to reclaim.

    ``recovered`` true means a send failed and was healed — the delay grows and no
    reclaim runs. False means a clean send; ``emptied`` then names the scenes whose
    frames the clean-cycle branch reclaims.
    """

    recovered: bool
    emptied: tuple[SceneId, ...]


@final
class HubReplicator:
    """The single background writer to the display connection.

    Composes the store's scene reader — its locked read side, so the worker takes
    exactly the reads it needs — the client provider, the dirty signal, and the
    ``SendRecovery`` that heals a failed send. ``mark_dirty`` / ``mark_menus`` are
    the surface tools and click dispatch call; the worker thread owns every send.
    """

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
    __slots__ = (
        "_attribution",
        "_backoff",
        "_callback_reader",
        "_clients",
        "_current_suspect",
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
        # Wire the tally reset to the store's quarantine-clear cascade so a
        # scene an owner fixes needs the full ATTRIBUTION_THRESHOLD again
        # rather than re-quarantining off one fresh death (a lingering
        # in-window tally would otherwise reach the threshold on the next
        # crash alone).
        quarantine.add_quarantine_cleared_observer(self._attribution.clear_tally)
        self._recovery = SendRecovery(
            clients, lifecycle, self._signal, self._attribution, RespawnBackoff()
        )
        self._thread = None
        self._backoff = _BASE_BACKOFF_SECONDS
        self._current_suspect = frozenset()
        return self

    # -- surface API: queue-only, called by tools and click dispatch --------

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Signal that ``scene_id`` changed. Queue-only — never sends."""
        self._signal.mark_dirty(scene_id)

    def mark_menus(self) -> None:
        """Signal that the menu registry changed. Queue-only — never sends.

        Payload-less: a menu change lands the same way a scene change does — the
        operation writes the Hub registry and flags it here, and this worker alone
        reads the registry fresh and sends it.
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

        The stop latches the dirty signal shutting, so a fresh thread would exit
        at once and every mark would silently go nowhere. The signal is the single
        source of that fact, so ``start`` and the worker's own exit can never
        disagree. luxd restarting is a new process, hence a new replicator, so this
        never blocks a real restart.
        """
        if self._signal.is_shutting:
            msg = "replicator was stopped; construct a fresh one to restart"
            raise RuntimeError(msg)

    def stop(self) -> None:
        """Flush pending, stop, and join. A stop is terminal, even before a start.

        Requesting the stop latches the dirty signal shutting, so any later
        ``start`` raises rather than spawning a worker that would exit at once.
        With no worker thread yet there is nothing to join, so a stop before a
        start is a clean no-op that still makes the replicator terminal.
        """
        self._signal.request_stop()
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

        Stability checks (isolation-exit and respawn-backoff reset) fire once
        per iteration, work or no work, so a quiet system where the last
        crasher was quarantined and no further write arrives still exits
        isolation once ``STABLE_INTERVAL`` has elapsed — the design's
        autonomous time-driven resumption, not gated on the next write. The
        idle-tick wake bounds the wait so the check actually runs on schedule.
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

        Three outcomes. A send failed and recovery handled it (a healed display and
        re-marked work) still counts as a failure, so the delay grows to throttle a
        display that connects yet refuses every send. A recovery step itself failed
        — an unspawnable display, a refused reconnect — or a non-socket error
        escaped: the exception reaches this outer guard, which restores the batch
        and backs off, unless this was the shutdown flush, whose work is dropped by
        design and only logged. A genuinely clean cycle resets the delay and only
        then reclaims the scenes it emptied — the reclaim is deferred to here so a
        later scene's failure in the same cycle cannot strand an already-reclaimed
        scene's frame. The stability-tick calls live in ``_run`` so they run per
        iteration whether or not a cycle ran.
        """
        try:
            outcome = self._push_cycle(batch)
        except Exception:
            if batch.shutting:
                logger.exception("replicator shutdown flush failed; dropping the batch")
                return
            logger.exception("replicator cycle failed; retrying the batch")
            self._recovery.restore(batch)
            self._back_off()
            return
        if outcome.recovered:
            if not batch.shutting:
                self._back_off()
            return
        self._backoff = _BASE_BACKOFF_SECONDS
        self._reclaim_emptied(outcome.emptied)

    def _push_cycle(self, batch: DrainedBatch) -> _CycleOutcome:
        """Send the cycle; heal a bounded send failure, else report the clean result.

        ``BlockingIOError`` (send timeout) is a wedged display, reaped and
        respawned; ``OSError`` (dead peer) only reconnects. Either way the death is
        attributed to ``_current_suspect`` — the whole batch in batching mode, or
        the one scene ``_attempt_isolating`` was probing — which ``_attempt`` sets
        immediately before each send that can raise, so it always reflects what was
        genuinely in flight at the failure. A recovery step that itself fails —
        reap/ensure raising, a refused reconnect — propagates to the caller's outer
        guard rather than being swallowed here.
        """
        try:
            emptied = self._attempt(batch)
        except BlockingIOError:
            self._recovery.recover(batch, wedged=True, suspect=self._current_suspect)
            return _CycleOutcome(recovered=True, emptied=())
        except OSError:
            self._recovery.recover(batch, wedged=False, suspect=self._current_suspect)
            return _CycleOutcome(recovered=True, emptied=())
        return _CycleOutcome(recovered=False, emptied=emptied)

    def _back_off(self) -> None:
        """Sleep the current retry delay, then grow it toward the cap."""
        time.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)

    def _attempt(self, batch: DrainedBatch) -> tuple[SceneId, ...]:
        """Send the cycle and return the scenes it found empty, for later reclaim.

        Quarantined scenes are filtered out before either send path runs — the
        load-bearing exclusion against the crash loop (Invariant 1: a quarantined
        scene is never replicated), enforced here regardless of what the dirty
        signal or a recovery re-mark queued. The menu send, when present, is
        deliberately attributed to the *empty* suspect set: a menu-caused crash
        is not a scene-caused crash, and the false-positive class isolation was
        written to prevent (an innocent scene coalesced with a crasher) reappears
        for every innocent live scene if a menu-poisoned send blames the whole
        batch. Menu-poison detection is a separate concern (attribution's design
        assumes scene-caused crashes); the empty suspect still trips isolation
        (any death does) so subsequent scene sends are singletons.
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

        A send failure anywhere in the loop aborts the whole method (an
        unhandled ``BlockingIOError``/``OSError`` propagates to ``_push_cycle``),
        so ``_current_suspect`` is set once, to the whole batch: a socket-level
        failure cannot tell which of several already-accepted sends is the one
        whose render actually crashed the Display.
        """
        self._current_suspect = scenes
        # Each ``_send_scene`` sends and reports whether the scene was empty; the
        # comprehension keeps the empties as reclaim candidates.
        return tuple(scene for scene in scenes if self._send_scene(scene))

    def _attempt_isolating(self, scenes: frozenset[SceneId]) -> tuple[SceneId, ...]:
        """Send every scene alone, with a liveness probe between sends.

        ``_current_suspect`` is narrowed to the singleton before each send, and
        a synchronous ``probe_alive`` runs *after* each send *before* the next
        one — the missing step under fire-and-forget alone. Without it, a scene
        N whose render crashes the display surfaces only as a broken pipe on
        the *next* write, and ``_current_suspect`` has already advanced to
        N+1: the death attributes to innocent N+1. The probe forces the crash
        to surface while ``_current_suspect`` is still {N}.

        A failed probe raises OSError (either its underlying send did, or the
        None pong is turned into one here), which ``_push_cycle`` catches and
        hands to recovery with the correct suspect.
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
        send happens with no store lock held — the store lock and the client send
        lock are never held together. An empty scene blanks its own frame.
        """
        snapshot = self._reader.snapshot(scene_id)
        snapshot.push(self._clients.get())
        return snapshot.is_empty

    def _reclaim_emptied(self, scenes: tuple[SceneId, ...]) -> None:
        """Forget each blanked scene's frame, re-checked still rootless under the lock.

        Deferred to a clean cycle so a failed send never reclaims a scene whose
        blank the recovery must retry. The rootless re-check keeps a re-show that
        landed during the send window: that re-show installed roots and a fresh
        frame, so the scene is no longer rootless and its new frame is kept.
        """
        for scene_id in scenes:
            self._reader.reclaim_if_rootless(scene_id)
