"""ServiceRunner: cancelling a job ends the ``bd`` it is waiting on, and only that.

The applet leaves by cancelling its tasks. A job parked on a worker thread cannot
be cancelled, so the runner ends the child that call started; the thread then
returns and the process can shut down by its ordinary path. The next call is a
different call and runs its own ``bd`` as if nothing had happened.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.applets.applet_board import AppletBoard
from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.latency import ClickLatency
from punt_lux.applets.runner import ServiceRunner
from punt_lux.apps.bd_command import BdOutput, BdRun, BoardScope
from punt_lux.apps.bd_exit import BdCancelledError
from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard

from .board_doubles import RecordingClient

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
        try:
            self._outcomes.append(
                BdRun().completed(BoardScope.for_board(all_issues=False))
            )
        except BdCancelledError as exc:
            self._outcomes.append(exc)
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
    assert isinstance(service.outcomes[0], BdCancelledError)


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


def _polling_bd(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``bd`` that waits, as its own child, until ``hang`` is gone, then answers."""
    started = directory / "started"
    hang = directory / "hang"
    hang.write_text("")
    script = directory / "bd"
    script.write_text(
        f'#!/bin/sh\necho $$ >> "{started}"\n'
        f'while [ -e "{hang}" ]; do sleep 0.05; done\necho "[]"\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    return started


def _running(started: Path) -> int:
    return len(started.read_text().split()) if started.exists() else 0


def test_cancelling_one_call_leaves_the_other_calls_bd_to_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _polling_bd(tmp_path, monkeypatch)
    cancelled = _BdBoundService()
    survivor = _BdBoundService()

    async def cancel_one_of_two() -> None:
        doomed = asyncio.ensure_future(_runner(cancelled).warmed())
        kept = asyncio.ensure_future(_runner(survivor).warmed())
        while _running(started) < 2:
            await asyncio.sleep(0.02)
        doomed.cancel()
        await asyncio.gather(doomed, return_exceptions=True)
        (tmp_path / "hang").unlink()
        await kept

    asyncio.run(cancel_one_of_two())

    assert isinstance(cancelled.outcomes[0], BdCancelledError)
    assert isinstance(survivor.outcomes[0], BdOutput)


def _beads_runner(client: object, monkeypatch: pytest.MonkeyPatch) -> ServiceRunner:
    """A runner over the real Beads service, whose Hub writes land on *client*.

    The recorder is structural, so it is handed over as the one thing it stands
    in for.
    """

    def no_luxd(_identity: object) -> object:
        return object()

    def recorder(_client: object) -> object:
        return client

    monkeypatch.setattr("punt_lux.applets.runner.LuxClient.for_identity", no_luxd)
    monkeypatch.setattr("punt_lux.applets.runner.ScopedBoardOps.for_client", recorder)
    load = BoardLoad(BeadsBoard.for_project("lux"), BeadsBrowser())
    service = BeadsService(AppletBoard(load, BoardSlot()))
    return _runner(cast("_BdBoundService", service))


def test_a_cold_click_cancelled_mid_query_pushes_no_failure_and_warns_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    started = _polling_bd(tmp_path, monkeypatch)
    client = RecordingClient()
    runner = _beads_runner(client, monkeypatch)

    async def leave_mid_click() -> None:
        job = asyncio.ensure_future(runner.clicked(ClickLatency("beads")))
        while not started.exists():
            await asyncio.sleep(0.02)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        (tmp_path / "hang").unlink()
        await asyncio.sleep(0.3)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(leave_mid_click())

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert len(client.scenes) == 1  # the placeholder, and no red message after it
    assert client.tables == []


def test_a_warm_up_cancelled_mid_query_warns_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    started = _polling_bd(tmp_path, monkeypatch)
    runner = _beads_runner(RecordingClient(), monkeypatch)

    async def leave_mid_warm_up() -> None:
        job = asyncio.ensure_future(runner.warmed())
        while not started.exists():
            await asyncio.sleep(0.02)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        (tmp_path / "hang").unlink()
        await asyncio.sleep(0.3)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(leave_mid_warm_up())

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert any(
        r.levelno == logging.DEBUG and "was cancelled" in r.getMessage()
        for r in caplog.records
    )
