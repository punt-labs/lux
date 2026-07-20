"""HubReplicator — the one background worker that writes to the display.

Every MCP mutation tool and every Hub-side click writes only to ``HubDisplay``
and marks the changed scene dirty; this worker alone sends those changes to the
display, and it alone handles a slow or dead one. So a stuck display can never
freeze an agent.

The worker waits on a condition, wakes when a scene is dirty or the screen was
cleared, coalesces a 16 ms burst, and drains the whole changed set. It blanks
first when a clear is pending — a ``clear`` then ``show`` in one window must
leave the new scene on screen — then repaints each scene from a copy the store
took under its read lock and handed out, so the store lock and the client send
lock are never held together. A send is
time-limited (``SO_SNDTIMEO`` on the socket): a wedged display raises
``BlockingIOError`` and the worker reaps and respawns it; a dead peer raises
``OSError`` and the worker reconnects. Both paths re-mark every live scene so the
fresh, empty display is repainted from the store.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.domain.hub.replicator_ports import (
        ClientProvider,
        DisplayLifecycle,
    )
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.ids import SceneId

logger = logging.getLogger(__name__)

# One frame at 60 fps: after a wake, wait this long so a burst of update() calls
# coalesces into a single resend.
_COALESCE_SECONDS = 0.016
# The send's own time limit is ~2 s (SO_SNDTIMEO); give reap the same budget.
_REAP_TIMEOUT = 2.0
# Bound the join at shutdown so a wedged final flush cannot hang the process.
_STOP_JOIN_TIMEOUT = 5.0


@final
@dataclass(frozen=True, slots=True)
class DrainedBatch:
    """One cycle's work: the coalesced scenes, whether a clear and a stop are due."""

    scenes: frozenset[SceneId]
    cleared: bool
    shutting: bool

    @property
    def has_work(self) -> bool:
        """Whether this cycle has anything to push."""
        return bool(self.scenes) or self.cleared


@final
class DirtySignal:
    """The changed-scene set, cleared flag, and stop flag under one condition.

    ``mark_dirty`` / ``mark_cleared`` are queue-only — they touch memory and
    notify, never any I/O — so a mutation tool returns the instant the store is
    updated. ``wait_and_drain`` is the worker's side: it blocks until there is
    work or a stop, coalesces a burst, then takes the whole set atomically.
    """

    _cond: threading.Condition
    _dirty: set[SceneId]
    _cleared: bool
    _shutting: bool
    __slots__ = ("_cleared", "_cond", "_dirty", "_shutting")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._dirty = set()
        self._cleared = False
        self._shutting = False
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Record a changed scene and wake the worker. Queue-only, no I/O."""
        with self._cond:
            self._dirty.add(scene_id)
            self._cond.notify()

    def mark_cleared(self) -> None:
        """Record that the screen was cleared and wake the worker. No I/O."""
        with self._cond:
            self._cleared = True
            self._cond.notify()

    def add_all(self, scenes: Iterable[SceneId]) -> None:
        """Re-mark a set of scenes dirty — the recovery re-mark after a respawn."""
        with self._cond:
            self._dirty.update(scenes)
            self._cond.notify()

    def request_stop(self) -> None:
        """Ask the worker to flush what is pending and stop."""
        with self._cond:
            self._shutting = True
            self._cond.notify()

    def wait_and_drain(self, coalesce_seconds: float) -> DrainedBatch:
        """Block until there is work or a stop, coalesce a burst, then drain.

        Returns the whole changed set and the cleared flag together, resetting
        both, so a mark that lands after the drain is carried to the next cycle.
        """
        with self._cond:
            while not self._dirty and not self._cleared and not self._shutting:
                self._cond.wait()
            if self._shutting and not self._dirty and not self._cleared:
                return DrainedBatch(frozenset(), cleared=False, shutting=True)
            self._cond.wait(coalesce_seconds)
            batch = DrainedBatch(
                frozenset(self._dirty),
                cleared=self._cleared,
                shutting=self._shutting,
            )
            self._dirty.clear()
            self._cleared = False
            return batch


@final
class HubReplicator:
    """The single background writer to the display connection.

    Composes the store's scene reader — its locked read side, so the worker
    takes exactly the reads it needs — the client provider, the display
    lifecycle, and the dirty signal. ``mark_dirty`` / ``mark_cleared`` are the
    surface tools and click dispatch call; the worker thread owns every send.
    """

    _reader: SceneReader
    _clients: ClientProvider
    _lifecycle: DisplayLifecycle
    _signal: DirtySignal
    _thread: threading.Thread | None
    __slots__ = ("_clients", "_lifecycle", "_reader", "_signal", "_thread")

    def __new__(
        cls,
        reader: SceneReader,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
        self._clients = clients
        self._lifecycle = lifecycle
        self._signal = DirtySignal()
        self._thread = None
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
        """Start the worker thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="lux-replicator", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the worker to flush pending scenes and stop, then join it."""
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
                try:
                    self._push_cycle(batch, recover=not batch.shutting)
                except Exception:
                    logger.exception("replicator cycle failed")
            if batch.shutting:
                return

    def _push_cycle(self, batch: DrainedBatch, *, recover: bool) -> None:
        """Blank first if cleared, then repaint each scene; recover on failure.

        ``BlockingIOError`` (send timeout) is caught before ``OSError`` (dead
        peer) because the former is a kind of the latter. During a clean
        shutdown ``recover`` is false: the final flush is best-effort and never
        reaps or reconnects.
        """
        try:
            if batch.cleared:
                self._clients.get().clear_async()
            for scene in batch.scenes:
                self._send_scene(scene)
        except BlockingIOError:
            if recover:
                self._recover_wedged()
        except OSError:
            if recover:
                self._recover_dead()

    def _send_scene(self, scene_id: SceneId) -> None:
        """Send a copy of the scene the store took under its read lock.

        The store returns a snapshot whose roots are already copied out, so the
        send happens with no store lock held — the store lock and the client send
        lock are never held together. A since-cleared scene snapshots empty and
        pushes nothing, so a drained mark never repaints a blank.
        """
        self._reader.snapshot(scene_id).push(self._clients.get())

    def _recover_wedged(self) -> None:
        """A wedged display: kill it, start a fresh one, reconnect, re-mark all."""
        self._lifecycle.reap(_REAP_TIMEOUT)
        self._lifecycle.ensure()
        self._clients.drop()
        self._remark_live_scenes()

    def _recover_dead(self) -> None:
        """A dead peer: drop the fd so the next send reconnects, then re-mark all."""
        self._clients.drop()
        self._remark_live_scenes()

    def _remark_live_scenes(self) -> None:
        """Re-mark every live scene so a fresh, empty display is repainted."""
        self._signal.add_all(self._reader.live_scene_ids())
