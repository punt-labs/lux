"""SendRecovery — heal the display after a send failure and re-mark the work.

When a send to the display fails, the worker hands the failure here, and what to do
is decided by the cause the dial recorded for its own end, not by the exception that
carried the failure. A display that stopped reading (recorded ``unresponsive``) is
killed — its launchd/systemd unit respawns it (lux-5uc7); the Hub never spawns a
competing process — and a dead peer (``OSError``) is only dropped so the next send
reconnects. Either way
the heal re-marks every live scene, a consumed clear, and the menu, so a display
that came back blank is fully repainted — scenes, the old clear, and the agent
bar alike.

If the heal itself cannot complete — the kill itself fails, a refused reconnect
— the worker instead restores the exact batch and backs off. ``restore`` is that
path: it puts the drained work back so nothing is lost.

Consolidated onto ``ClientRegistry._connect_and_reconcile`` (DES-068):
``recover`` calls ``self._clients.asks()`` right after ``drop()``, which is
the one code path that declares the fresh connection's manifest and marks
every live scene plus the menu dirty. This class no longer reads
``live_scene_ids()`` or marks live scenes itself — it only re-marks the
menu unconditionally and re-queues the failed batch's own scenes, since a
scene the batch emptied has no roots and so is absent from
``live_scene_ids()``; that is a guarantee specific to *this* failed batch,
not a duplicate of the connect-success hook's policy.

The one kill a wedged death drives is paced through
:class:`~punt_lux.domain.hub.respawn_backoff.RespawnBackoff` rather than the
send-retry backoff, whose reset-on-clean-send condition fires too eagerly under
isolation. Blame for a death is not this class's concern: the crash-loop quarantine
charges each dead dial's own ledger when the next push starts.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import HubRetiredError
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff

if TYPE_CHECKING:
    from punt_lux.domain.hub.batch_sender import BatchSendError
    from punt_lux.domain.hub.dirty_signal import DirtySignal, DrainedBatch
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle

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
    _respawn: RespawnBackoff
    __slots__ = ("_clients", "_lifecycle", "_respawn", "_signal")

    def __new__(
        cls,
        clients: ClientProvider,
        lifecycle: DisplayLifecycle,
        signal: DirtySignal,
        respawn: RespawnBackoff,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._lifecycle = lifecycle
        self._signal = signal
        self._respawn = respawn
        return self

    @classmethod
    def pacing_respawns(
        cls, clients: ClientProvider, lifecycle: DisplayLifecycle, signal: DirtySignal
    ) -> Self:
        """Build the recovery that paces respawns with a fresh ``RespawnBackoff``."""
        return cls(clients, lifecycle, signal, RespawnBackoff())

    def recover(self, batch: DrainedBatch, failure: BatchSendError) -> None:
        """Heal the display after ``failure``, then re-mark the failed batch.

        A shutdown flush — the batch's shutting flag — is best-effort: it logs and
        leaves the display as-is rather than reaping or reconnecting, since the
        process is going away, and is not attributed — the process is exiting on
        purpose, not crashing. Reading the flag from the batch here makes that
        policy unbypassable by the caller.

        A failure whose cause is a :class:`HubRetiredError` says nothing about the
        display, so nothing is reaped or dropped: the dial is redialed and the batch
        repainted. Any other failure is a death: a ``BlockingIOError`` (a send
        timeout) is recorded by the dial as an unresponsive display, killed so its
        service unit respawns it when it is this host's own; any other ``OSError`` is
        a dead peer, only dropped. Who is to blame for it is not decided here: the
        dial left its own record, which the next push charges before it sends
        anything (see :class:`~punt_lux.domain.hub.batch_sender.BatchSender`), so a
        scene that reaches the threshold is excluded from the very batch this
        repaints.

        The failure's ``dial`` is the dial the failed send went out on (``None`` if
        none was had); only it is dropped, and only if no redial has replaced it.

        ``asks()`` after the heal is the one DES-068 connect-success hook
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
        if not isinstance(failure.cause, HubRetiredError):
            self._heal(failure)
        self._clients.asks()  # redials: the connect-success hook repaints
        self._repaint(batch)

    def _heal(self, failure: BatchSendError) -> None:
        """Reap a wedged display and drop the dial the send failed on.

        What the failure was is read from the dial's own record of who ended it, not
        from the exception that carried it: a write cut short before its first byte
        (``BlockingIOError``), one cut short half way (``TornStreamError``) and a
        display that never acked all left the dial ``unresponsive``. A dial to a
        Display on another host is only dropped: the reap kills the local socket's
        owner, and that is not the Display that stalled.
        """
        dial = failure.dial
        if dial is None:
            return  # nothing was dialed: nothing to reap or to drop
        if dial.ended == "unresponsive" and dial.reaches_local_display():
            time.sleep(self._respawn.note_respawn())
            self._lifecycle.reap(_REAP_TIMEOUT)
        self._clients.drop(dial)

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
        if batch.menus_dirty:
            self._signal.mark_menus()
        self._signal.add_all(batch.scenes)

    def _repaint(self, batch: DrainedBatch) -> None:
        """Re-mark the batch's scenes and the menu so the fresh display repaints.

        The menu flag makes the worker read the registry fresh at the next send,
        so a change during the failed send wins. The heal path always sets it;
        ``restore`` only when the batch itself carried one.
        """
        self._signal.mark_menus()
        self._signal.add_all(batch.scenes)
