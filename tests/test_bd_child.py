"""BdChild and BdLeash: a call's cancellation ends that call's ``bd`` and no other.

The stand-in ``bd`` is a script that records its start and then sleeps, so the
condition is the one a slow hosted database makes -- a child in flight -- without
a database and without a clock to race.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.apps.bd_child import BdChild, BdLeash
from punt_lux.apps.bd_command import BdOutput, BdRun, BoardScope
from punt_lux.apps.bd_exit import BdCancelledError, BdExit

if TYPE_CHECKING:
    from collections.abc import Callable

_SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]
_QUICK = [sys.executable, "-c", "print('done')"]
_JOIN_SECONDS = 10


def _silent_bd(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a ``bd`` on PATH that signals it has started, then never answers."""
    started = directory / "started"
    script = directory / "bd"
    script.write_text(f'#!/bin/sh\necho $$ > "{started}"\nexec sleep 60\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    return started


def _bd_with_grandchild(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """A ``bd`` whose child holds its pipes, so ending ``bd`` alone is not enough."""
    started = directory / "started"
    grandchild = directory / "grandchild"
    script = directory / "bd"
    script.write_text(
        f'#!/bin/sh\nsleep 60 &\necho $! > "{grandchild}"\n'
        f'echo $$ > "{started}"\nwait\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    return started, grandchild


def _scope() -> BoardScope:
    return BoardScope.for_board(all_issues=False)


def _await(path: Path) -> None:
    """Block until the stand-in ``bd`` has announced it is running."""
    waiting = threading.Event()
    while not path.exists() and not waiting.wait(0.02):
        pass


def _in_thread(work: Callable[[], None]) -> threading.Thread:
    worker = threading.Thread(target=work)
    worker.start()
    return worker


def test_cancel_ends_the_attached_child() -> None:
    leash = BdLeash()
    child = BdChild(_SLEEP, leash)

    leash.cancel()

    with pytest.raises(BdCancelledError):
        child.output(_JOIN_SECONDS)


def test_a_child_started_after_cancel_is_ended_and_reads_as_cancelled() -> None:
    leash = BdLeash()
    leash.cancel()

    child = BdChild(_SLEEP, leash)

    with pytest.raises(BdCancelledError):
        child.output(_JOIN_SECONDS)


def test_a_finished_child_is_left_alone_by_cancel() -> None:
    leash = BdLeash()
    child = BdChild(_QUICK, leash)
    exit_ = child.output(_JOIN_SECONDS)

    leash.cancel()

    assert exit_.stdout.strip() == "done"


def test_cancel_with_no_child_is_a_no_op() -> None:
    BdLeash().cancel()


def test_cancel_ends_every_child_the_call_started() -> None:
    leash = BdLeash()
    first = BdChild(_SLEEP, leash)
    second = BdChild(_SLEEP, leash)

    leash.cancel()

    with pytest.raises(BdCancelledError):
        first.output(_JOIN_SECONDS)
    with pytest.raises(BdCancelledError):
        second.output(_JOIN_SECONDS)


def test_one_child_finishing_does_not_release_another_the_call_still_runs() -> None:
    leash = BdLeash()
    slow = BdChild(_SLEEP, leash)
    BdChild(_QUICK, leash).output(_JOIN_SECONDS)

    leash.cancel()

    with pytest.raises(BdCancelledError):
        slow.output(_JOIN_SECONDS)


def test_a_thread_nobody_bound_a_leash_to_gets_one_nothing_holds() -> None:
    first = BdLeash.current()
    second = BdLeash.current()

    assert first is not second


def test_an_unheld_leash_is_never_cancelled() -> None:
    assert not BdLeash.current().cancelled


def test_a_bound_leash_is_the_current_one() -> None:
    leash = BdLeash()

    with leash.bound():
        assert BdLeash.current() is leash

    assert BdLeash.current() is not leash


def test_a_worker_thread_the_call_hands_a_job_to_carries_its_leash() -> None:
    leash = BdLeash()
    seen: list[BdLeash] = []

    async def serve() -> None:
        await leash.served(lambda: seen.append(BdLeash.current()))

    asyncio.run(serve())

    assert seen == [leash]


def test_a_thread_started_by_hand_does_not_carry_the_leash() -> None:
    leash = BdLeash()
    seen: list[BdLeash] = []

    with leash.bound():
        _in_thread(lambda: seen.append(BdLeash.current())).join()

    assert seen[0] is not leash


def test_cancelling_ends_a_bd_that_never_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _silent_bd(tmp_path, monkeypatch)
    leash = BdLeash()
    outcome: list[BaseException] = []

    def work() -> None:
        try:
            BdChild(_scope().argv(), leash).output(60)
        except BdCancelledError as exc:
            outcome.append(exc)

    worker = _in_thread(work)
    _await(started)

    leash.cancel()
    worker.join(timeout=_JOIN_SECONDS)

    assert not worker.is_alive()
    assert isinstance(outcome[0], BdCancelledError)


def test_cancelling_reaches_a_grandchild_holding_the_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, _ = _bd_with_grandchild(tmp_path, monkeypatch)
    leash = BdLeash()

    def work() -> None:
        with pytest.raises(BdCancelledError):
            BdChild(_scope().argv(), leash).output(60)

    worker = _in_thread(work)
    _await(started)

    leash.cancel()
    worker.join(timeout=_JOIN_SECONDS)

    assert not worker.is_alive()


def test_a_timeout_reaches_a_grandchild_holding_the_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bd_with_grandchild(tmp_path, monkeypatch)
    raised: list[BaseException] = []

    def work() -> None:
        try:
            BdChild(_scope().argv(), BdLeash()).output(0.5)
        except subprocess.TimeoutExpired as exc:
            raised.append(exc)

    worker = _in_thread(work)
    worker.join(timeout=_JOIN_SECONDS)

    assert not worker.is_alive()
    assert isinstance(raised[0], subprocess.TimeoutExpired)


def test_a_child_that_will_not_die_is_logged_and_the_wait_still_ends(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    child = BdChild(_SLEEP, BdLeash())
    ending = BdChild.end

    def does_not_end(_child: BdChild) -> None:
        return None

    monkeypatch.setattr(BdChild, "end", does_not_end)
    monkeypatch.setattr("punt_lux.apps.bd_child._REAP_SECONDS", 0.2)

    with caplog.at_level(logging.ERROR), pytest.raises(subprocess.TimeoutExpired):
        child.output(0.2)

    ending(child)
    assert "did not exit" in caplog.text
    assert str(child.pid) in caplog.text


def test_a_run_under_a_cancelled_leash_never_waits_on_bd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _silent_bd(tmp_path, monkeypatch)
    leash = BdLeash()
    leash.cancel()

    with leash.bound(), pytest.raises(BdCancelledError):
        BdRun().completed(_scope())


def test_a_run_cancelled_mid_flight_is_cancelled_not_a_bd_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _silent_bd(tmp_path, monkeypatch)
    leash = BdLeash()
    outcome: list[object] = []

    def work() -> None:
        with leash.bound():
            try:
                outcome.append(BdRun().completed(_scope()))
            except BdCancelledError as exc:
                outcome.append(exc)

    worker = _in_thread(work)
    _await(started)

    leash.cancel()
    worker.join(timeout=_JOIN_SECONDS)

    assert isinstance(outcome[0], BdCancelledError)


def test_a_run_that_answers_is_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "bd"
    script.write_text('#!/bin/sh\necho "[]"\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

    assert isinstance(BdRun().completed(_scope()), BdOutput)


def test_a_cancelled_calls_ended_bd_is_logged_at_debug_not_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    started = _silent_bd(tmp_path, monkeypatch)
    leash = BdLeash()

    async def serve_then_cancel() -> None:
        job = asyncio.ensure_future(
            leash.served(lambda: BdRun().completed(_scope()) and None)
        )
        while not started.exists():
            await asyncio.sleep(0.02)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        await asyncio.sleep(0.3)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(serve_then_cancel())

    messages = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert (logging.DEBUG, "the call was cancelled; its bd was ended") in messages
    assert all(level < logging.WARNING for level, _ in messages)


def test_the_exit_is_an_immutable_value() -> None:
    exit_ = BdChild(_QUICK, BdLeash()).output(_JOIN_SECONDS)

    assert isinstance(exit_, BdExit)
    assert exit_.returncode == 0
    with pytest.raises(AttributeError):
        exit_.returncode = 1  # type: ignore[misc]


def test_a_nonzero_exit_is_a_value_not_an_exception() -> None:
    failing = [sys.executable, "-c", "import sys; sys.exit(3)"]

    exit_ = BdChild(failing, BdLeash()).output(_JOIN_SECONDS)

    assert exit_.returncode == 3
