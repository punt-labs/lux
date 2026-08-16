"""SendRecovery — heal the display after a send failure and re-mark the work.

When a send to the display fails, the worker hands the failure here. A wedged
display (send timeout, ``BlockingIOError``) is killed and respawned; a dead peer
(``OSError``) is only dropped so the next send reconnects. Either way the heal
re-marks every live scene, a consumed clear, and the menu, so a display that came
back blank is fully repainted — scenes, the old clear, and the agent bar alike.

If the heal itself cannot complete — an unspawnable display, a refused reconnect
— the worker instead restores the exact batch and backs off. ``restore`` is that
path: it puts the drained work back so nothing is lost.

Consolidated onto ``ClientRegistry._connect_and_reconcile`` (DES-068):
``recover`` calls ``self._clients.get()`` right after ``drop()``, which is
the one code path that declares the fresh connection's manifest and marks
every live scene plus the menu dirty. This class no longer reads
``live_scene_ids()`` or marks live scenes itself — it only re-marks the
menu unconditionally and re-queues the failed batch's own scenes, since a
scene the batch emptied has no roots and so is absent from
``live_scene_ids()``; that is a guarantee specific to *this* failed batch,
not a duplicate of the connect-success hook's policy.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.dirty_signal import DirtySignal, DrainedBatch
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle
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
    __slots__ = ("_clients", "_lifecycle", "_signal")

    def __new__(
        cls,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
        signal: DirtySignal,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._lifecycle = lifecycle
        self._signal = signal
        return self

    def recover(self, batch: DrainedBatch, *, wedged: bool) -> None:
        """Heal the display, then re-mark this batch so nothing it carried is lost.

        A shutdown flush — the batch's shutting flag — is best-effort: it logs and
        leaves the display as-is rather than reaping or reconnecting, since the
        process is going away. Reading the flag from the batch here makes that
        policy unbypassable by the caller.

        ``get()`` right after ``drop()`` is the one DES-068 connect-success hook
        (``ClientRegistry._connect_and_reconcile``): it declares the fresh
        connection's manifest and marks every live scene plus the menu dirty, so
        this class does not enumerate live scenes itself. It only re-queues the
        batch's own scenes on top — a scene the batch emptied has no roots, so
        it is absent from that hook's live-scene set, and its lost blank would
        never resend without this.
        """
        if batch.shutting:
            logger.warning("replicator shutdown flush failed; display left as-is")
            return
        if wedged:
            self._lifecycle.reap(_REAP_TIMEOUT)
            self._lifecycle.ensure()
        self._clients.drop()
        self._clients.get()
        self._requeue(batch.scenes, menus_dirty=True)

    def restore(self, batch: DrainedBatch) -> None:
        """Put a failed batch back on the queue so the next cycle retries it."""
        self._requeue(batch.scenes, menus_dirty=batch.menus_dirty)

    def _requeue(self, scenes: frozenset[SceneId], *, menus_dirty: bool) -> None:
        """Re-mark scenes and the menu flag onto the signal.

        When set, the menu flag makes the worker read the registry fresh at the
        next send, so a change during the failed send wins. The heal path always
        sets it; restore only when the batch itself carried one.
        """
        if menus_dirty:
            self._signal.mark_menus()
        self._signal.add_all(scenes)
