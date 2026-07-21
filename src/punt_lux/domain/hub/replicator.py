"""HubReplicator — the one background worker that writes to the display.

Every MCP mutation tool and every Hub-side click writes only to ``HubDisplay``
and marks the changed scene dirty; this worker alone sends those changes to the
display, and it alone handles a slow or dead one. So a stuck display can never
freeze an agent.

The worker waits on a ``DirtySignal``, wakes when a scene is dirty or the screen
was cleared, coalesces a 16 ms burst, and drains the whole changed set. It blanks
first when a clear is pending — a ``clear`` then ``show`` in one window must leave
the new scene on screen — then repaints each scene from a copy the store took
under its read lock and handed out, so the store lock and the client send lock are
never held together. A send is time-limited (``SO_SNDTIMEO`` on the socket): a
wedged display raises ``BlockingIOError`` and a dead peer raises ``OSError``, and
either failure is handed to ``SendRecovery``, which heals the display and re-marks
the work. A recovery that cannot heal the display restores the batch and backs
off, so nothing drained is ever lost.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.dirty_signal import DirtySignal
from punt_lux.domain.hub.recovery import SendRecovery

if TYPE_CHECKING:
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.replicator_ports import (
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
    ``SendRecovery`` that heals a failed send. ``mark_dirty`` / ``mark_cleared``
    are the surface tools and click dispatch call; the worker thread owns every
    send.
    """

    _reader: SceneReader
    _menu_reader: MenuReader
    _clients: ClientProvider
    _signal: DirtySignal
    _recovery: SendRecovery
    _thread: threading.Thread | None
    _backoff: float
    __slots__ = (
        "_backoff",
        "_clients",
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
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
        self._menu_reader = menu_reader
        self._clients = clients
        self._signal = DirtySignal()
        self._recovery = SendRecovery(clients, lifecycle, self._signal, reader)
        self._thread = None
        self._backoff = _BASE_BACKOFF_SECONDS
        return self

    # -- surface API: queue-only, called by tools and click dispatch --------

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Signal that ``scene_id`` changed. Queue-only — never sends."""
        self._signal.mark_dirty(scene_id)

    def mark_cleared(self) -> None:
        """Signal that the screen was cleared. Queue-only — never sends."""
        self._signal.mark_cleared()

    def mark_menus(self) -> None:
        """Signal that the menu registry changed. Queue-only — never sends.

        Payload-less, like ``mark_cleared``: a menu change lands the same way a
        scene change does — the operation writes the Hub registry and flags it
        here, and this worker alone reads the registry fresh and sends it.
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
        """Drain-and-push until asked to stop, surviving any single-cycle error."""
        while True:
            batch = self._signal.wait_and_drain(_COALESCE_SECONDS)
            if batch.has_work:
                self._run_cycle(batch)
            if batch.shutting:
                return

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
        scene's frame.
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
        respawned; ``OSError`` (dead peer) only reconnects. A recovery step that
        itself fails — reap/ensure raising, a refused reconnect — propagates to the
        caller's outer guard rather than being swallowed here.
        """
        try:
            emptied = self._attempt(batch)
        except BlockingIOError:
            self._recovery.recover(batch, wedged=True)
            return _CycleOutcome(recovered=True, emptied=())
        except OSError:
            self._recovery.recover(batch, wedged=False)
            return _CycleOutcome(recovered=True, emptied=())
        return _CycleOutcome(recovered=False, emptied=emptied)

    def _back_off(self) -> None:
        """Sleep the current retry delay, then grow it toward the cap."""
        time.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)

    def _attempt(self, batch: DrainedBatch) -> tuple[SceneId, ...]:
        """Send the cycle and return the scenes it found empty, for later reclaim.

        When the batch carried a clear, ``clear_async`` already blanked the whole
        display, so an empty scene in the batch is skipped rather than re-blanked;
        otherwise an empty scene is pushed to blank its own frame. Either way an
        empty scene is a reclaim candidate — its frame is dead once the display is
        blank — so it is collected regardless of the clear.
        """
        if batch.cleared:
            self._clients.get().clear_async()
        if batch.menus_dirty:
            # Read the registry fresh, so the newest menu state wins even if a
            # change landed after this batch was drained.
            state = self._menu_reader.wire_snapshot()
            sender = self._clients.get()
            sender.set_menu([dict(menu) for menu in state.bar])
            sender.set_registered_items([dict(item) for item in state.items])
        # Each ``_send_scene`` sends and reports whether the scene was empty; the
        # comprehension keeps the empties as reclaim candidates.
        return tuple(
            scene
            for scene in batch.scenes
            if self._send_scene(scene, blank_empty=not batch.cleared)
        )

    def _send_scene(self, scene_id: SceneId, *, blank_empty: bool) -> bool:
        """Send a copy of the scene; return whether it was empty (a reclaim candidate).

        The store returns a snapshot whose roots are already copied out, so the
        send happens with no store lock held — the store lock and the client send
        lock are never held together. An empty scene blanks its frame unless the
        cycle already blanked the whole display with a clear.
        """
        snapshot = self._reader.snapshot(scene_id)
        snapshot.push(self._clients.get(), blank_empty=blank_empty)
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
