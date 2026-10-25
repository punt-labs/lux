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

from punt_lux.domain.hub.batch_sender import BatchSender, BatchSendError
from punt_lux.domain.hub.crash_attribution import CrashAttribution
from punt_lux.domain.hub.dirty_signal import DirtySignal
from punt_lux.domain.hub.disconnected_retry import DisconnectedRetry
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import QuarantinePort
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.frame_owner_facts import FrameOwnerFactsReader
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
    _clients: ClientProvider
    _signal: DirtySignal
    _recovery: SendRecovery
    _attribution: CrashAttribution
    _sender: BatchSender
    _thread: threading.Thread | None
    _backoff: float
    _disconnected_retry: DisconnectedRetry
    __slots__ = (
        "_attribution",
        "_backoff",
        "_clients",
        "_disconnected_retry",
        "_reader",
        "_recovery",
        "_sender",
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
        owner_facts: FrameOwnerFactsReader,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
        self._clients = clients
        self._signal = DirtySignal()
        self._attribution = CrashAttribution(quarantine)
        self._sender = BatchSender(
            reader,
            menu_reader,
            callback_reader,
            clients,
            clients.take_writer(),  # the one writer: nothing else is given the seat
            self._attribution,
            owner_facts,
        )
        # Wire the tally reset to the quarantine-clear cascade so a fixed
        # scene needs the full ATTRIBUTION_THRESHOLD again, not one fresh
        # death against a lingering in-window tally.
        quarantine.add_quarantine_cleared_observer(self._attribution.clear_tally)
        self._recovery = SendRecovery(
            clients, lifecycle, self._signal, RespawnBackoff()
        )
        self._thread = None
        self._backoff = _BASE_BACKOFF_SECONDS
        # A second, independently-tuned pacer for the never-connected case.
        self._disconnected_retry = DisconnectedRetry.paced(
            base_delay=_DISCONNECTED_BASE_DELAY_SECONDS,
            max_delay=_DISCONNECTED_MAX_DELAY_SECONDS,
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
        """Charge any death found while idle, then decay per-episode state.

        A display that died while nothing was queued leaves its record on the dial;
        charging it here, every tick, means no redial by anyone else can hide it.
        The two death-free-interval checks follow.
        """
        self._sender.charge_deaths()
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
        ``OSError`` is healed by ``SendRecovery`` (a wedged display reaped, a
        dead peer reconnected, a Hub-retired dial redialed without blame); a
        death is charged from its own dial's ledger, however it was found."""
        since_gen = self._clients.reconnect_generation  # BEFORE the attempt: race-safe
        try:
            emptied = self._sender.push(batch)
        except DisplayNotConnectedError:
            self._recovery.restore(batch)
            if not batch.shutting:
                self._disconnected_retry.wait(self._clients, since_gen=since_gen)
            return _CycleOutcome(outcome="disconnected")
        except BatchSendError as exc:
            return self._recovered(batch, exc, since_gen)
        return _CycleOutcome(outcome="clean", emptied=emptied)

    def _recovered(
        self, batch: DrainedBatch, failure: BatchSendError, since_gen: int
    ) -> _CycleOutcome:
        """Heal after a failed send; a display that is down is the disconnected path.

        The heal may find nobody to redial: the display died and stayed down. That
        is paced as the display being down and the batch held for its return, not
        logged as a replicator cycle that crashed.
        """
        try:
            self._recovery.recover(batch, failure)
        except DisplayNotConnectedError:
            self._recovery.restore(batch)
            if not batch.shutting:
                self._disconnected_retry.wait(self._clients, since_gen=since_gen)
            return _CycleOutcome(outcome="disconnected")
        return _CycleOutcome(outcome="recovered")

    def _back_off(self) -> None:
        """Sleep the current retry delay, then grow it toward the cap."""
        time.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)

    @property
    def disconnected_delay(self) -> float:
        """Return the current not-connected retry delay, in seconds (design §9)."""
        return self._disconnected_retry.current_delay

    def _reclaim_emptied(self, scenes: tuple[SceneId, ...]) -> None:
        """Forget each blanked scene's frame, re-checked rootless under the lock.

        Deferred to a clean cycle so a failed send never reclaims a scene the
        recovery must retry. The rootless re-check keeps a re-show that landed
        during the send window: it installed roots and a new frame, so the
        scene is no longer rootless and that new frame is kept.
        """
        for scene_id in scenes:
            self._reader.reclaim_if_rootless(scene_id)
