"""SendRecovery — heal the display after a send failure and re-mark the work.

When a send to the display fails, the worker hands the failure here. A wedged
display (send timeout, ``BlockingIOError``) is killed and respawned; a dead peer
(``OSError``) is only dropped so the next send reconnects. Either way every live
scene is re-marked so a fresh display is repainted, and a consumed clear is
re-marked so a same-display reconnect does not leave the old scene on screen.

If the heal itself cannot complete — an unspawnable display, a refused reconnect
— the worker instead restores the exact batch and backs off. ``restore`` is that
path: it puts the drained work back so nothing is lost.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.dirty_signal import DirtySignal, DrainedBatch
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.ids import SceneId

logger = logging.getLogger(__name__)

# The send's own time limit is ~2 s (SO_SNDTIMEO); give reap the same budget.
_REAP_TIMEOUT = 2.0

__all__ = ["SendRecovery"]


@final
class SendRecovery:
    """Reap/respawn or reconnect the display, then re-mark the work to repaint."""

    _clients: ClientProvider
    _lifecycle: DisplayLifecycle
    _signal: DirtySignal
    _reader: SceneReader
    __slots__ = ("_clients", "_lifecycle", "_reader", "_signal")

    def __new__(
        cls,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
        signal: DirtySignal,
        reader: SceneReader,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._lifecycle = lifecycle
        self._signal = signal
        self._reader = reader
        return self

    def recover(self, batch: DrainedBatch, *, wedged: bool) -> None:
        """Heal the display and re-mark the work so nothing is lost.

        A wedged display is killed and respawned; a dead peer is only dropped so
        the next send reconnects. A shutdown flush — the batch's shutting flag —
        is best-effort: it logs and leaves the display as-is rather than reaping or
        reconnecting, since the process is going away. Reading the flag from the
        batch here makes that policy unbypassable by the caller.
        """
        if batch.shutting:
            logger.warning("replicator shutdown flush failed; display left as-is")
            return
        if wedged:
            self._lifecycle.reap(_REAP_TIMEOUT)
            self._lifecycle.ensure()
        self._clients.drop()
        self._remark(batch)

    def restore(self, batch: DrainedBatch) -> None:
        """Put a failed batch back on the queue so the next cycle retries it."""
        self._requeue(batch.scenes, cleared=batch.cleared)

    def _remark(self, batch: DrainedBatch) -> None:
        """Re-mark the live scenes, the batch's own scenes, and a consumed clear.

        The batch's own scenes join the live ones because a scene the batch
        emptied has no roots — it is not in ``live_scene_ids`` — so without this
        its blank push would be lost on a reconnect and stale content would linger
        in that frame. The clear is re-marked because a reconnect to the same
        display leaves the old scenes on screen; without blanking again a
        cleared-but-rendered scene would linger forever. Blank-then-repaint is
        idempotent.
        """
        scenes = frozenset(self._reader.live_scene_ids()) | batch.scenes
        self._requeue(scenes, cleared=batch.cleared)

    def _requeue(self, scenes: frozenset[SceneId], *, cleared: bool) -> None:
        """Re-mark a set of scenes, and a consumed clear, back onto the signal."""
        if cleared:
            self._signal.mark_cleared()
        self._signal.add_all(scenes)
