"""SendRecovery — heal the display after a send failure and re-mark the work.

When a send to the display fails, the worker hands the failure here. A wedged
display (send timeout, ``BlockingIOError``) is killed and respawned; a dead peer
(``OSError``) is only dropped so the next send reconnects. Either way the heal
re-marks every live scene, a consumed clear, and the menu, so a display that came
back blank is fully repainted — scenes, the old clear, and the agent bar alike.

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

        A shutdown flush — the batch's shutting flag — is best-effort: it logs and
        leaves the display as-is rather than reaping or reconnecting, since the
        process is going away. Reading the flag from the batch here makes that
        policy unbypassable by the caller.
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
        self._requeue(
            batch.scenes, cleared=batch.cleared, menus_dirty=batch.menus_dirty
        )

    def _remark(self, batch: DrainedBatch) -> None:
        """Re-mark the live scenes, the batch's own scenes, a clear, and the menu.

        An emptied scene the batch drained has no roots, so it is absent from
        ``live_scene_ids``; re-marking the batch's scenes keeps its lost blank
        queued. The clear is re-marked so a same-display reconnect blanks again
        rather than leaving the old scene up (blank-then-repaint is idempotent).
        The menu is re-marked unconditionally because a respawn or a reconnect onto
        a new process comes back with no agent bar, and the handshake replays only
        the World-menu items, never ``set_menu``; the fresh registry read at send
        time supplies the current bar, or a harmless blank if none is set.
        """
        scenes = frozenset(self._reader.live_scene_ids()) | batch.scenes
        self._requeue(scenes, cleared=batch.cleared, menus_dirty=True)

    def _requeue(
        self,
        scenes: frozenset[SceneId],
        *,
        cleared: bool,
        menus_dirty: bool,
    ) -> None:
        """Re-mark scenes, a consumed clear, and the menu flag onto the signal.

        When set, the menu flag makes the worker read the registry fresh at the
        next send, so a change during the failed send wins. The heal path always
        sets it; restore only when the batch itself carried one.
        """
        if cleared:
            self._signal.mark_cleared()
        if menus_dirty:
            self._signal.mark_menus()
        self._signal.add_all(scenes)
