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
# refused reconnect), wait this long before retrying so the worker never spins.
_RETRY_BACKOFF_SECONDS = 0.1


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
    _stopped: bool
    __slots__ = ("_clients", "_reader", "_recovery", "_signal", "_stopped", "_thread")

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
        self._stopped = False
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
        """Reject a restart of a stopped worker — a stopped replicator is terminal.

        Its dirty signal is latched to shutting, so a fresh thread would exit at
        once and every mark would silently go nowhere. luxd restarting is a new
        process, hence a new replicator, so this never blocks a real restart.
        """
        if self._stopped:
            msg = "replicator was stopped; construct a fresh one to restart"
            raise RuntimeError(msg)

    def stop(self) -> None:
        """Flush pending, stop, and join; a joined stop is terminal, else startable."""
        self._signal.request_stop()
        thread = self._thread
        if thread is not None:
            self._stopped = True
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
        """Push the batch, recover from a send failure, and never lose the batch.

        The worker's own top-level guard: a recovery step that itself fails — an
        unspawnable display, a refused reconnect — or a send raising anything
        other than a socket error must not drop the drained work. The batch is
        put back and the worker backs off, so a display that cannot start retries
        without spinning. A clean-shutdown cycle keeps neither: it is the last one.
        """
        try:
            self._push_cycle(batch)
        except Exception:
            logger.exception("replicator cycle failed; retrying the batch")
            if not batch.shutting:
                self._recovery.restore(batch)
                time.sleep(_RETRY_BACKOFF_SECONDS)

    def _push_cycle(self, batch: DrainedBatch) -> None:
        """Blank first if cleared, then repaint each scene; recover on a failure.

        ``BlockingIOError`` (send timeout) is caught before ``OSError`` (dead
        peer) because the former is a kind of the latter. A shutdown batch is
        the last one: recovery is inactive, so the final flush is best-effort
        and never reaps or reconnects.
        """
        active = not batch.shutting
        try:
            self._attempt(batch)
        except BlockingIOError:
            self._recovery.recover(batch, wedged=True, active=active)
        except OSError:
            self._recovery.recover(batch, wedged=False, active=active)

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
        """
        self._reader.snapshot(scene_id).push(
            self._clients.get(), blank_empty=blank_empty
        )
