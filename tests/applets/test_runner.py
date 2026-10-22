"""ServiceRunner: cancelling a job ends the ``bd`` it is waiting on, and only that.

The applet leaves by cancelling its tasks. A job parked on a worker thread cannot
be cancelled, so the runner ends the child that call started; the thread then
returns and the process can shut down by its ordinary path. The next call is a
different call and runs its own ``bd`` as if nothing had happened.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.runner import ServiceRunner
from punt_lux.apps.bd_command import BdOutput, BdRun, BoardScope
from punt_lux.apps.beads_result import BeadsFailure

if TYPE_CHECKING:
    import pytest

    from punt_lux.applets.service import AppletService


@final
class _BdBoundService:
    """A service whose warm-up is one ``bd`` query, whatever ``bd`` does."""

    _outcomes: list[object]
    _returned: threading.Event
    __slots__ = ("_outcomes", "_returned")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._outcomes = []
        self._returned = threading.Event()
        return self

    @property
    def returned(self) -> threading.Event:
        return self._returned

    @property
    def outcomes(self) -> list[object]:
        return self._outcomes

    def prefetch(self) -> None:
        self._outcomes.append(BdRun().completed(BoardScope.for_board(all_issues=False)))
        self._returned.set()


def _runner(service: _BdBoundService) -> ServiceRunner:
    identity = AppletIdentity.for_session("lux-beads", 1).client
    return ServiceRunner(identity, cast("AppletService", service))


def _bd(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``bd`` that hangs while ``hang`` exists and answers ``[]`` once it is gone."""
    started = directory / "started"
    hang = directory / "hang"
    hang.write_text("")
    script = directory / "bd"
    script.write_text(
        f'#!/bin/sh\necho $$ > "{started}"\n'
        f'if [ -e "{hang}" ]; then exec sleep 60; fi\necho "[]"\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    return started


def test_cancelling_the_warm_up_ends_the_bd_it_waits_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _bd(tmp_path, monkeypatch)
    service = _BdBoundService()
    runner = _runner(service)

    async def leave_mid_query() -> None:
        job = asyncio.ensure_future(runner.warmed())
        while not started.exists():
            await asyncio.sleep(0.02)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)

    asyncio.run(leave_mid_query())

    assert service.returned.is_set()
    assert isinstance(service.outcomes[0], BeadsFailure)


def test_a_cancelled_call_does_not_stop_the_next_from_running_bd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _bd(tmp_path, monkeypatch)
    first = _BdBoundService()
    second = _BdBoundService()

    async def cancel_one_then_run_another() -> None:
        job = asyncio.ensure_future(_runner(first).warmed())
        while not started.exists():
            await asyncio.sleep(0.02)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        (tmp_path / "hang").unlink()
        await _runner(second).warmed()

    asyncio.run(cancel_one_then_run_another())

    assert isinstance(second.outcomes[0], BdOutput)
