"""Run Hub workers and telemetry for the ASGI application lifetime."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.hub import hub_display, hub_lifecycle
from punt_lux.hub.display_workers import display_workers
from punt_lux.hub.expiry_sweep import ExpirySweep
from punt_lux.hub.lease_reap_sweep import LeaseReapSweep
from punt_lux.hub.peripherals import peripherals
from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.kernel.usage import capture_usage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

    from punt_lux.kernel.hub_paths import HubPaths

logger = logging.getLogger(__name__)


class _PeriodicSweep(Protocol):
    """A wait-sweep-repeat background task — ``ExpirySweep`` and ``LeaseReapSweep``."""

    async def run(self) -> None:
        """Run until cancelled."""
        ...


@asynccontextmanager
async def _periodic_sweep_running(
    sweep: _PeriodicSweep, *, name: str
) -> AsyncGenerator[asyncio.Task[None]]:
    """Run one periodic sweep for the block, cancelled and awaited on exit.

    A task that died with an exception re-raises it on await; that is logged
    and swallowed so the caller's own shutdown always continues.
    """
    task = asyncio.create_task(sweep.run())
    try:
        yield task
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except ProgrammerError:
            raise
        except Exception:
            logger.exception("%s sweep task failed before shutdown", name)


@final
class HubLifespan:
    """Own workers, telemetry and Hub runtime files."""

    __slots__ = ("_paths",)
    _paths: HubPaths

    def __new__(cls, paths: HubPaths) -> Self:
        self = super().__new__(cls)
        self._paths = paths
        return self

    def record_listening(self, port: int) -> int:
        """Publish the bound port and process ID, then return the process ID."""
        self._paths.prepare()
        port_path = self._paths.port_path
        port_path.write_text(str(port))
        logger.info("Wrote port file: %s (port %d)", port_path, port)
        pid = os.getpid()
        self._paths.pid_path.write_text(str(pid))
        return pid

    @asynccontextmanager
    async def run(self, _app: FastAPI) -> AsyncGenerator[None]:
        """Stop workers and flush telemetry before uvicorn replays a signal."""
        with capture_usage():
            async with self._workers():
                yield

    @asynccontextmanager
    async def _workers(self) -> AsyncGenerator[None]:
        peripherals.start()
        expiry = ExpirySweep(hub_display.frames, display_workers.replicator)
        lease_reap = LeaseReapSweep(hub_lifecycle)
        try:
            # Both sweeps are cancelled and awaited on exit, before the
            # replicator stops; the lease reap has no dependency on it, so
            # the two nest in either order.
            async with (
                _periodic_sweep_running(expiry, name="frame-expiry"),
                _periodic_sweep_running(lease_reap, name="lease-reap"),
            ):
                yield
        finally:
            peripherals.stop()
            self._remove_port_file()
            self._paths.pid_path.unlink(missing_ok=True)

    def _remove_port_file(self) -> None:
        port_path = self._paths.port_path
        try:
            port_path.unlink(missing_ok=True)
            logger.info("Removed port file: %s", port_path)
        except OSError:
            logger.warning("Could not remove port file: %s", port_path)
