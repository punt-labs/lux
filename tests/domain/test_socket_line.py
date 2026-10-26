"""SocketLine: a wait for the socket lock is cut by silence, never by elapsed time."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from punt_lux.domain.hub import socket_line
from punt_lux.domain.hub.socket_line import SocketLine
from tests.domain.display_double import Call

if TYPE_CHECKING:
    import pytest


def _window(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    monkeypatch.setattr(socket_line, "SCENE_WRITE_DEADLINE_SECONDS", seconds)


def test_a_free_line_is_taken_at_once() -> None:
    line = SocketLine()

    assert line.acquire_unless_silent()
    line.release()


def test_a_line_held_with_no_byte_moving_is_given_up_after_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    assert line.acquire_within(1.0)  # held, and nothing moves

    waiting = Call(line.acquire_unless_silent)

    assert waiting.wait(3.0), "the wait for the lock never ended"
    assert waiting.result is False
    line.release()


def test_a_line_held_by_a_holder_that_keeps_moving_is_waited_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    assert line.acquire_within(1.0)
    stop = threading.Event()

    def keeps_moving() -> None:
        end = time.monotonic() + 0.6  # four windows: elapsed time alone would cut it
        while time.monotonic() < end:
            line.moved()
            stop.wait(0.03)
        line.release()

    mover = threading.Thread(target=keeps_moving, daemon=True)
    mover.start()
    waiting = Call(line.acquire_unless_silent)

    assert waiting.wait(5.0), "the wait for the lock never ended"
    assert waiting.result is True
    mover.join(2.0)
    line.release()


def test_progress_is_seen_for_the_window_after_a_byte_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    line.moved()

    assert line.is_progressing()
    time.sleep(0.25)
    assert not line.is_progressing()
