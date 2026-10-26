"""The store lock rule is enforced at runtime, in both directions."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.element_invocation_resolver import ResolvedInteraction
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.hub.lock_discipline import LockDiscipline, LockDisciplineError
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol import PingMessage, ReadyMessage
from punt_lux.protocol.elements import ButtonElement

if TYPE_CHECKING:
    from collections.abc import Iterator


class _Dial:
    """A generation and the display's end of its socket pair."""

    def __init__(self) -> None:
        ours, self.display = socket.socketpair()
        self.generation = DialGeneration(
            HandshakeResult(sock=ours, endpoint="pair", ready=ReadyMessage()),
            lambda _g, _c: True,
            lambda _g, _c: True,
        )


@pytest.fixture
def dial() -> Iterator[_Dial]:
    made = _Dial()
    yield made
    made.generation.shut()
    made.display.close()


def _interaction() -> ResolvedInteraction:
    return ResolvedInteraction(
        element=ButtonElement(id="b", label="x"), owner=None, scene_id=SceneId("s")
    )


def _click() -> ButtonClicked:
    return ButtonClicked(
        element_id=ElementId("b"), scene_id=SceneId("s"), owner_id=ClientId("o")
    )


class TestTheStoreLockRecordsItsHolder:
    def test_a_thread_holds_it_exactly_as_long_as_it_is_inside(self) -> None:
        lock = StoreLock()
        assert not LockDiscipline.holds_store()

        with lock.write(), lock.read():
            assert LockDiscipline.holds_store()
        assert not LockDiscipline.holds_store()

    def test_an_exception_releases_it(self) -> None:
        lock = StoreLock()
        with pytest.raises(RuntimeError), lock.write():
            raise RuntimeError

        assert not LockDiscipline.holds_store()


class TestFiringRequiresTheStoreWriteLock:
    def test_a_handler_fired_without_the_lock_is_refused(self) -> None:
        with pytest.raises(LockDisciplineError, match="firing a handler"):
            _interaction().fire(_click(), lambda _e, _p: None)

    def test_a_handler_fired_under_the_lock_runs(self) -> None:
        with StoreLock().write():
            _interaction().fire(_click(), lambda _e, _p: None)


class TestTheDialSocketLockIsNeverTakenUnderTheStoreLock:
    def test_a_write_under_the_store_lock_is_refused(self, dial: _Dial) -> None:
        with StoreLock().write(), pytest.raises(LockDisciplineError):
            dial.generation.send(PingMessage(ts=1.0))

    def test_a_read_under_the_store_lock_is_refused(self, dial: _Dial) -> None:
        dial.display.send(b"x")  # readable: the poll goes on to take the lock
        with StoreLock().write(), pytest.raises(LockDisciplineError):
            dial.generation.poll_chunk(0.5)

    def test_a_drain_under_the_store_lock_is_refused(self, dial: _Dial) -> None:
        dial.display.send(b"x")
        with StoreLock().write(), pytest.raises(LockDisciplineError):
            dial.generation.drain()

    def test_the_same_write_outside_the_store_lock_is_fine(self, dial: _Dial) -> None:
        dial.generation.send(PingMessage(ts=1.0))
