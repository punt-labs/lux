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
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.dirty_signal import DirtySignal
from punt_lux.domain.hub.recovery import SendRecovery

if TYPE_CHECKING:
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle
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
class HubReplicator:
    """The single background writer to the display connection.

    Composes the store's scene reader — its locked read side, so the worker takes
    exactly the reads it needs — the client provider, the dirty signal, and the
    ``SendRecovery`` that heals a failed send. ``mark_dirty`` / ``mark_cleared``
    are the surface tools and click dispatch call; the worker thread owns every
    send.
    """

    _reader: SceneReader
    _clients: ClientProvider
    _signal: DirtySignal
    _recovery: SendRecovery
    _thread: threading.Thread | None
    _backoff: float
    __slots__ = (
        "_backoff",
        "_clients",
        "_reader",
        "_recovery",
        "_signal",
        "_thread",
    )

    def __new__(
        cls,
        reader: SceneReader,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
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
        """Push the batch; on an unhandled failure restore it and back off.

        The worker's top-level guard: a recovery step that itself fails — an
        unspawnable display, a refused reconnect — or a send raising anything other
        than a socket error must not kill the worker or drop the drained work. A
        shutdown flush is the last cycle, so its work is dropped by design and only
        logged; any other failure puts the batch back and grows the delay — doubling
        to the cap — so a persistently unspawnable display retries at a sane rate
        rather than a firehose. A clean cycle resets the delay so a recovered
        display responds promptly again.
        """
        try:
            self._push_cycle(batch)
        except Exception:
            if batch.shutting:
                logger.exception("replicator shutdown flush failed; dropping the batch")
                return
            logger.exception("replicator cycle failed; retrying the batch")
            self._recovery.restore(batch)
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)
        else:
            self._backoff = _BASE_BACKOFF_SECONDS

    def _push_cycle(self, batch: DrainedBatch) -> None:
        """Blank first if cleared, then repaint each scene; recover on a failure.

        ``BlockingIOError`` (send timeout) is caught before ``OSError`` (dead
        peer) because the former is a kind of the latter. ``recover`` reads the
        batch's shutting flag itself, so a shutdown flush is best-effort — it
        never reaps or reconnects — without the caller having to say so.
        """
        try:
            self._attempt(batch)
        except BlockingIOError:
            self._recovery.recover(batch, wedged=True)
        except OSError:
            self._recovery.recover(batch, wedged=False)

    def _attempt(self, batch: DrainedBatch) -> None:
        """Send the cycle: blank first when cleared, then repaint each scene.

        When the batch carried a clear, ``clear_async`` already blanked the whole
        display, so an empty scene in the batch is skipped rather than re-blanked;
        otherwise an empty scene is pushed to blank its own frame.
        """
        if batch.cleared:
            self._clients.get().clear_async()
        for scene in batch.scenes:
            self._send_scene(scene, blank_empty=not batch.cleared)

    def _send_scene(self, scene_id: SceneId, *, blank_empty: bool) -> None:
        """Send a copy of the scene the store took under its read lock.

        The store returns a snapshot whose roots are already copied out, so the
        send happens with no store lock held — the store lock and the client send
        lock are never held together. An empty scene blanks its frame unless the
        cycle already blanked the whole display with a clear.

        Once that blank lands, the scene's presentation is reclaimed: the scene is
        gone from the store, and nothing repaints it without a re-show that records
        a fresh presentation, so the entry is dead weight. The reclaim runs only
        after a successful blank, so a failed send keeps the presentation for the
        recovery re-mark to blank again.
        """
        snapshot = self._reader.snapshot(scene_id)
        snapshot.push(self._clients.get(), blank_empty=blank_empty)
        if blank_empty and snapshot.is_empty:
            self._reader.reclaim(scene_id)
