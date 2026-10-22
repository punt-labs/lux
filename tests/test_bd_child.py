"""BdChild and BdLeash: a call's cancellation ends that call's ``bd`` and no other.

The stand-in ``bd`` is a script that records its start and then sleeps, so the
condition is the one a slow hosted database makes -- a child in flight -- without
a database and without a clock to race.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from punt_lux.apps.bd_child import BdChild, BdLeash
from punt_lux.apps.bd_command import BdRun, BoardScope
from punt_lux.apps.beads_result import BeadsFailure

if TYPE_CHECKING:
    import pytest

_SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


def _silent_bd(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a ``bd`` on PATH that signals it has started, then never answers."""
    started = directory / "started"
    script = directory / "bd"
    script.write_text(f'#!/bin/sh\necho $$ > "{started}"\nexec sleep 60\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    return started


def _scope() -> BoardScope:
    return BoardScope.for_board(all_issues=False)


def test_cancel_ends_the_attached_child() -> None:
    leash = BdLeash()
    process = subprocess.Popen(_SLEEP, text=True)
    assert leash.attach(process)

    leash.cancel()

    assert process.wait(timeout=10) != 0


def test_a_child_attached_after_cancel_is_ended_and_refused() -> None:
    leash = BdLeash()
    leash.cancel()
    process = subprocess.Popen(_SLEEP, text=True)

    assert not leash.attach(process)
    assert process.wait(timeout=10) != 0


def test_a_detached_child_is_left_alone_by_cancel() -> None:
    leash = BdLeash()
    process = subprocess.Popen(_SLEEP, text=True)
    leash.attach(process)
    leash.detach()

    leash.cancel()

    assert process.poll() is None
    process.kill()
    process.wait(timeout=10)


def test_cancel_with_no_child_is_a_no_op() -> None:
    BdLeash().cancel()


def test_a_thread_with_no_bound_leash_gets_one_nothing_holds() -> None:
    first = BdLeash.current()
    second = BdLeash.current()

    assert first is not second


def test_a_bound_leash_is_the_current_one() -> None:
    leash = BdLeash()

    with leash.bound():
        assert BdLeash.current() is leash

    assert BdLeash.current() is not leash


def test_cancelling_ends_a_bd_that_never_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = _silent_bd(tmp_path, monkeypatch)
    leash = BdLeash()
    outcome: list[object] = []

    def work() -> None:
        child = BdChild(_scope().argv(), leash)
        child.output(60)
        outcome.append(child.returncode)

    worker = threading.Thread(target=work)
    worker.start()
    deadline = threading.Event()
    while not started.exists() and not deadline.wait(0.02):
        pass

    leash.cancel()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert outcome[0] != 0


def test_a_run_under_a_cancelled_leash_never_waits_on_bd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _silent_bd(tmp_path, monkeypatch)
    leash = BdLeash()
    leash.cancel()

    with leash.bound():
        outcome = BdRun().completed(_scope())

    assert isinstance(outcome, BeadsFailure)
