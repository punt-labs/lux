"""SocketLine: a wait for the socket lock is cut by silence, never by elapsed time."""

from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub import socket_line
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.hub.socket_line import SocketLine
from punt_lux.domain.hub.store_lock import StoreLock
from tests.domain.display_double import Call

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _window(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    monkeypatch.setattr(socket_line, "SCENE_WRITE_DEADLINE_SECONDS", seconds)


def _write_wait(line: SocketLine) -> bool:
    """Wait for the line as a writer does; whether it was got."""
    with line.writing() as free:
        return free


class _Holder:
    """A thread holding a line until it is let go, and the line's moving, if asked."""

    def __init__(self, line: SocketLine, *, keep_moving_for: float = 0.0) -> None:
        self._release = threading.Event()
        self._held = threading.Event()
        self._line = line
        self._moving = keep_moving_for
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._held.wait(3.0), "the line was never taken"

    def _run(self) -> None:
        with self._line.draining(1.0) as free:
            assert free
            self._held.set()
            end = time.monotonic() + self._moving
            while time.monotonic() < end:
                self._line.moved()
                self._release.wait(0.03)
            self._release.wait(3.0)

    def let_go(self) -> None:
        self._release.set()
        self._thread.join(3.0)


@pytest.fixture
def holders() -> Iterator[list[_Holder]]:
    made: list[_Holder] = []
    yield made
    for holder in made:
        holder.let_go()


def test_a_free_line_is_taken_at_once() -> None:
    line = SocketLine()

    with line.writing() as free:
        assert free


def test_the_line_is_let_go_when_the_door_closes() -> None:
    line = SocketLine()
    with line.writing():
        pass

    with line.draining(1.0) as free:
        assert free


def test_the_line_is_let_go_when_the_body_raises() -> None:
    line = SocketLine()
    with pytest.raises(RuntimeError), line.reading():
        raise RuntimeError

    with line.draining(1.0) as free:
        assert free


def test_a_line_held_with_no_byte_moving_is_given_up_after_the_window(
    monkeypatch: pytest.MonkeyPatch, holders: list[_Holder]
) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    holders.append(_Holder(line))  # held, and nothing moves

    waiting = Call(lambda: _write_wait(line))

    assert waiting.wait(3.0), "the wait for the lock never ended"
    assert waiting.result is False


def test_a_line_held_by_a_holder_that_keeps_moving_is_waited_for(
    monkeypatch: pytest.MonkeyPatch, holders: list[_Holder]
) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    # Four windows of moving: elapsed time alone would cut the wait.
    holders.append(_Holder(line, keep_moving_for=0.6))
    holders[0].let_go()  # lets go once it has stopped moving

    waiting = Call(lambda: _write_wait(line))

    assert waiting.wait(5.0), "the wait for the lock never ended"
    assert waiting.result is True


def test_a_drain_that_finds_the_line_held_past_its_timeout_is_told_so(
    holders: list[_Holder],
) -> None:
    line = SocketLine()
    holders.append(_Holder(line))

    with line.draining(0.05) as free:
        assert not free


def test_progress_is_seen_for_the_window_after_a_byte_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    line.moved()

    assert line.is_progressing()
    time.sleep(0.25)
    assert not line.is_progressing()


def test_an_idle_line_held_briefly_is_not_refused_to_a_writer(
    monkeypatch: pytest.MonkeyPatch, holders: list[_Holder]
) -> None:
    _window(monkeypatch, 0.2)
    line = SocketLine()
    time.sleep(0.3)  # idle: nothing has moved for longer than D
    holder = _Holder(line)  # a reader takes the line for a non-blocking recv
    holders.append(holder)
    threading.Timer(0.01, holder.let_go).start()  # and lets go 10 ms later

    assert _write_wait(line) is True


def test_taking_the_line_is_not_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    time.sleep(0.25)

    with line.writing() as free:
        assert free

    assert not line.is_progressing()


def _idle_line_and_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SocketLine, socket.socket, socket.socket]:
    _window(monkeypatch, 0.15)
    line = SocketLine()
    time.sleep(0.25)  # nothing has moved for D
    ours, theirs = socket.socketpair()
    return line, ours, theirs


class TestWhatTheKeepaliveTakesForLife:
    def test_a_write_that_completed_is_no_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line, ours, theirs = _idle_line_and_pair(monkeypatch)
        with ours, theirs, line.writing() as free:
            assert free
            line.send(ours, b"x")

        assert not line.is_progressing()

    def test_a_write_in_progress_leaves_the_keepalive_no_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line, ours, theirs = _idle_line_and_pair(monkeypatch)
        with ours, theirs, line.writing() as free:
            assert free
            line.send(ours, b"x")

            assert line.is_progressing()

    def test_a_write_that_stalled_leaves_the_keepalive_its_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line, ours, theirs = _idle_line_and_pair(monkeypatch)
        with ours, theirs, line.writing() as free:
            assert free
            line.send(ours, b"x")
            time.sleep(0.25)  # no byte moves for longer than D

            assert not line.is_progressing()

    def test_a_write_keeps_a_waiter_for_the_line_waiting(
        self, monkeypatch: pytest.MonkeyPatch, holders: list[_Holder]
    ) -> None:
        # The bytes of a write are not evidence of life, but a wait behind it is
        # still re-armed by them: that is the other purpose of the one clock.
        _window(monkeypatch, 0.15)
        line = SocketLine()
        holders.append(_Holder(line, keep_moving_for=0.5))
        holders[0].let_go()

        assert _write_wait(line) is True

    def test_an_incoming_byte_is_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line, ours, theirs = _idle_line_and_pair(monkeypatch)
        ours.close()
        theirs.close()
        line.moved()

        assert line.is_progressing()


def _under_the_store_lock(door: Callable[[SocketLine], object]) -> None:
    with StoreLock().write(), pytest.raises(LockDisciplineError):
        door(SocketLine())


class TestEveryDoorRefusesTheStoreLock:
    def test_reading(self) -> None:
        _under_the_store_lock(lambda line: line.reading().__enter__())

    def test_draining(self) -> None:
        _under_the_store_lock(lambda line: line.draining(0.0).__enter__())

    def test_writing(self) -> None:
        _under_the_store_lock(lambda line: line.writing().__enter__())

    def test_waiting_for_readability(self) -> None:
        ours, theirs = socket.socketpair()
        try:
            _under_the_store_lock(lambda line: line.readable(ours, 0.0))
        finally:
            ours.close()
            theirs.close()


def test_the_line_offers_no_door_that_is_not_a_context_manager() -> None:
    public = {name for name in vars(SocketLine) if not name.startswith("_")}

    assert public == {
        "readable",
        "reading",
        "draining",
        "writing",
        "moved",
        "is_progressing",
        "send",
    }
