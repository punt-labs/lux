"""Keep the Hub's terminal windows equal to the daemon's running sessions."""

from __future__ import annotations

import asyncio
import logging
from typing import Self

from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.pty.listed_session import ListedSession
from punt_lux.pty.session_watch import SessionWatch
from punt_lux.pty.sync_plan import SyncPlan
from punt_lux.pty.terminal_windows import TerminalWindows, WindowRefusedError
from punt_lux.wire.stream.session_events import SessionEvent

logger = logging.getLogger(__name__)

_POLL_S = 0.1  # twice this fits in the helper's 0.3 s shutdown grace
_RETRY_S = 2.0
_MAX_RETRY_S = 30.0
_SHUTDOWN_CLEAR_S = 0.2


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
        """Watch and reconcile for ever; cancellation or a programmer error ends it.

        Any failure is logged and retried. A failure that repeats with the same
        reason is reported once and retried at a growing interval. Cancellation at
        any point, the retry sleep included, takes the windows down before it ends
        the task.
        """
        delay, last = _RETRY_S, ""
        try:
            while True:
                try:
                    await self._watch()
                    delay, last = _RETRY_S, ""
                except ProgrammerError:
                    raise
                except (OSError, SessionRefusedError, WindowRefusedError) as error:
                    repeated = str(error) == last
                    self._report_expected(error, repeated=repeated)
                    delay, last = self._backed_off(delay, str(error), repeated=repeated)
                except Exception as error:
                    logger.exception("Terminal keeper failed unexpectedly (%s)", error)
                    delay, last = self._backed_off(delay, str(error), repeated=False)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            await self._take_down_windows()
            raise

    async def _take_down_windows(self) -> None:
        """Remove this helper's windows as it stops; their shells stop with it.

        Without this the Hub keeps the windows of terminals that no longer run,
        and no later helper owns them to remove them. The Hub is read first, so a
        window published as the keeper was cancelled is removed too.
        """
        try:
            async with asyncio.timeout(_SHUTDOWN_CLEAR_S):
                await self._windows.refresh()
                await self._windows.clear()
        except (TimeoutError, WindowRefusedError) as error:
            logger.warning("Terminal windows left behind at shutdown: %s", error)

    @staticmethod
    def _backed_off(delay: float, reason: str, *, repeated: bool) -> tuple[float, str]:
        return (min(delay * 2, _MAX_RETRY_S) if repeated else _RETRY_S), reason

    @staticmethod
    def _report_expected(error: Exception, *, repeated: bool) -> None:
        if isinstance(error, OSError) or isinstance(error.__cause__, OSError):
            logger.debug("Terminal watch lost (%s); reconciling shortly", error)
        else:
            (logger.debug if repeated else logger.warning)(
                "Terminal watch lost (%s); reconciling shortly", error
            )

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
