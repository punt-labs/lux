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

The one respawn a wedged death drives is also where the crash-loop quarantine
lives (display-crash-quarantine.md): ``recover`` attributes the death to its
caller-determined suspect set — the whole batch in the replicator's batching
mode, a probed singleton in isolation mode — before healing, and paces a
respawn through :class:`~punt_lux.domain.hub.respawn_backoff.RespawnBackoff`
rather than the send-retry backoff, whose reset-on-clean-send condition fires
too eagerly under isolation.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import CrashAttribution
    from punt_lux.domain.hub.dirty_signal import DirtySignal, DrainedBatch
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle
    from punt_lux.domain.hub.respawn_backoff import RespawnBackoff
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
    _attribution: CrashAttribution
    _respawn: RespawnBackoff
    __slots__ = ("_attribution", "_clients", "_lifecycle", "_respawn", "_signal")

    def __new__(
        cls,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
        signal: DirtySignal,
        attribution: CrashAttribution,
        respawn: RespawnBackoff,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._lifecycle = lifecycle
        self._signal = signal
        self._attribution = attribution
        self._respawn = respawn
        return self

    def recover(
        self,
        batch: DrainedBatch,
        *,
        wedged: bool,
        suspect: frozenset[SceneId],
        render_error: str | None = None,
    ) -> None:
        """Attribute the death, heal the display, then re-mark the failed batch.

        A shutdown flush — the batch's shutting flag — is best-effort: it logs and
        leaves the display as-is rather than reaping or reconnecting, since the
        process is going away, and is not attributed — the process is exiting on
        purpose, not crashing. Reading the flag from the batch here makes that
        policy unbypassable by the caller.

        ``suspect`` is whatever the caller determined was in flight when the send
        failed: the whole batch in batching mode, or the one scene being probed in
        isolation mode (display-crash-quarantine.md Question 1). ``render_error``
        is the message of the exception that surfaced the death (an OSError /
        BlockingIOError from the failed send or probe); the attribution passes
        it into the ``QuarantineRecord`` so an agent whose scene later crosses
        the threshold sees WHY it was quarantined, not just that it was.
        Attributing runs before healing so a scene that just reached the
        threshold is quarantined, and therefore excluded from replication,
        before the re-mark below.

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
        self._attribution.attribute_death(suspect, render_error=render_error)
        if wedged:
            time.sleep(self._respawn.note_respawn())
            self._lifecycle.reap(_REAP_TIMEOUT)
            self._lifecycle.ensure()
        self._clients.drop()
        self._clients.get()
        self._requeue(batch.scenes, menus_dirty=True)

    def reset_backoff_if_stable(self) -> None:
        """Reset the respawn backoff once the Display has served stably.

        Called by the replicator on every clean cycle — not on the send itself,
        since a clean *send* is too eager a reset condition under isolation
        (see the module docstring) — so the pacing only relaxes once the Display
        has demonstrably stopped dying.
        """
        self._respawn.reset_if_stable()

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
