"""Keep the Hub's terminal windows equal to the daemon's running sessions."""

from __future__ import annotations

import asyncio
import logging
from typing import Self

from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.pty.listed_session import ListedSession
from punt_lux.pty.session_watch import SessionWatch
from punt_lux.pty.sync_plan import SyncPlan
from punt_lux.pty.terminal_windows import TerminalWindows, WindowRefusedError
from punt_lux.wire.stream.session_events import SessionEvent

logger = logging.getLogger(__name__)

_POLL_S = 0.5
_RETRY_S = 2.0


class TerminalKeeper:
    """Reconcile on every connect, then follow the daemon's events.

    The daemon's list is the authority. Any lost watch, daemon restart, Hub
    restart (``resync``) or failed application re-dials and reconciles, so a
    missed event never strands a window.
    """

    _daemon: DaemonExchange
    _windows: TerminalWindows
    _stale: asyncio.Event

    def __new__(cls, daemon: DaemonExchange, windows: TerminalWindows) -> Self:
        self = super().__new__(cls)
        self._daemon, self._windows = daemon, windows
        self._stale = asyncio.Event()
        return self

    def resync(self) -> None:
        """Ask for a reconcile at the next opportunity; the Hub may have lost scenes."""
        self._stale.set()

    async def serve(self) -> None:
        """Watch and reconcile for ever; only cancellation ends it."""
        while True:
            try:
                await self._watch()
            except (OSError, SessionRefusedError, WindowRefusedError) as error:
                logger.exception("Terminal watch lost (%s); reconciling shortly", error)
            await asyncio.sleep(_RETRY_S)

    async def _watch(self) -> None:
        watch = await asyncio.to_thread(SessionWatch.open, self._daemon)
        try:
            self._stale.clear()
            listing = await asyncio.to_thread(watch.listing)
            await self._windows.refresh()
            plan = SyncPlan.reconcile(
                listing.running, watch.drain(), self._windows.shown
            )
            await self._windows.apply(plan)
            while not self._stale.is_set():
                for event in await asyncio.to_thread(watch.events, _POLL_S):
                    await self._follow(event)
        finally:
            watch.close()

    async def _follow(self, event: SessionEvent) -> None:
        if event.kind == "ended":
            await self._windows.close(event.session)
        else:
            await self._windows.open(
                ListedSession(event.session, event.label, "running")
            )
