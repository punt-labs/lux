"""The store lock rule is enforced at runtime, in both directions."""

from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.batch_transaction import BatchTransaction
from punt_lux.domain.hub.dial_generation import DialEnds, DialGeneration
from punt_lux.domain.hub.element_invocation_resolver import ResolvedInteraction
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.hub.lock_discipline import LockDiscipline
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
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
            DialEnds(retire=lambda _g, _c: True, by_writer=lambda _g, _c: True),
        )


@pytest.fixture
def dial() -> Iterator[_Dial]:
    made = _Dial()
    yield made
    made.generation.shut()
    made.display.close()


_TRANSACTION = BatchTransaction(lambda _e, _p: None, lambda _w: None)


def _interaction(store: StoreLock) -> ResolvedInteraction:
    return ResolvedInteraction(
        element=ButtonElement(id="b", label="x"),
        owner=None,
        scene_id=SceneId("s"),
        store_guard=store.write(),
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
            _interaction(StoreLock()).fire(_click(), _TRANSACTION)

    def test_a_handler_fired_under_the_lock_runs(self) -> None:
        store = StoreLock()
        with store.write():
            _interaction(store).fire(_click(), _TRANSACTION)

    def test_a_handler_fired_under_another_stores_lock_is_refused(self) -> None:
        walked, other = StoreLock(), StoreLock()

        with other.write(), pytest.raises(LockDisciplineError, match="firing"):
            _interaction(walked).fire(_click(), _TRANSACTION)


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

    def test_a_poll_on_a_quiet_socket_is_refused_the_first_time_it_runs(
        self, dial: _Dial
    ) -> None:
        with StoreLock().write(), pytest.raises(LockDisciplineError):
            dial.generation.poll_chunk(0.01)  # nothing readable: still a break

    def test_a_drain_on_a_quiet_socket_is_refused_the_first_time_it_runs(
        self, dial: _Dial
    ) -> None:
        with StoreLock().write(), pytest.raises(LockDisciplineError):
            dial.generation.drain()

    def test_the_same_write_outside_the_store_lock_is_fine(self, dial: _Dial) -> None:
        dial.generation.send(PingMessage(ts=1.0))


class TestTheCountCannotBeCorrupted:
    def test_it_belongs_to_one_lock_not_to_every_lock(self) -> None:
        mine, other = StoreLock().write(), StoreLock().write()

        with mine:
            assert (mine.holds_here(), other.holds_here()) == (True, False)
            assert LockDiscipline.holds_store()  # the discipline asks every lock

    def test_it_belongs_to_one_thread(self) -> None:
        guard = StoreLock().write()
        seen: list[bool] = []

        with guard:
            looking = threading.Thread(target=lambda: seen.append(guard.holds_here()))
            looking.start()
            looking.join(3.0)

        assert not looking.is_alive()
        assert seen == [False]

    def test_letting_go_of_a_lock_never_taken_raises(self) -> None:
        guard = StoreLock().write()

        with pytest.raises(LockDisciplineError, match="does not hold"):
            guard.__exit__(None, None, None)

        with guard:  # the count did not go below zero: the next hold is seen
            assert guard.holds_here()

    def test_the_discipline_only_reads_the_count(self) -> None:
        public = {name for name in vars(LockDiscipline) if not name.startswith("_")}

        assert public == {"holds_store", "require_store", "forbid_store"}
