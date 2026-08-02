"""SessionWatch — the promise an applet makes to leave when its session does.

The window is the poll interval, so these drive the watch with a short one and
assert what it decides, never how long it took.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from punt_lux.applets.watch import NoSession, SessionEnd, SessionWatch


def _ended_process() -> int:
    """Return the pid of a process that has exited and been reaped."""
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


def test_a_live_session_is_alive() -> None:
    assert SessionWatch(os.getpid()).session_is_alive is True


def test_a_session_that_has_gone_is_not() -> None:
    assert SessionWatch(_ended_process()).session_is_alive is False


def test_a_session_this_process_may_not_signal_still_counts_as_alive() -> None:
    """Existence is the question, not permission — pid 1 is running, not ours."""
    assert SessionWatch(1).session_is_alive is True


def test_the_watch_returns_once_the_session_is_gone() -> None:
    watch = SessionWatch(_ended_process(), poll_seconds=0.01)
    asyncio.run(asyncio.wait_for(watch.until_session_ends(), timeout=5))


def test_the_watch_keeps_waiting_while_the_session_lives() -> None:
    """The bound is the poll interval; until it lapses the applet keeps serving."""
    watch = SessionWatch(os.getpid(), poll_seconds=0.01)
    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(watch.until_session_ends(), timeout=0.1))


def test_an_unwatched_applet_is_never_ended_by_the_watch() -> None:
    """Run by hand, the terminal is the tie — nothing here invents a deadline."""
    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(NoSession().until_session_ends(), timeout=0.1))


def test_both_watches_answer_the_same_question() -> None:
    assert isinstance(SessionWatch(os.getpid()), SessionEnd)
    assert isinstance(NoSession(), SessionEnd)
