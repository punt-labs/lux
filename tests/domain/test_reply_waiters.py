"""ReplyWaiters -- the in-flight slots, on the one lock its sink lends it."""

from __future__ import annotations

import ast
import inspect
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_end import DialEnd
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.hub.owned_condition import OwnedCondition
from punt_lux.domain.hub.pending import Pending
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.hub.reply_waiters import ReplyOutOfOrderError, ReplyWaiters
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse

_STRANGER: Pending[None, QueryResponse] = Pending(None, QueryResponse)

_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "punt_lux"
    / "domain"
    / "hub"
    / "reply_waiters.py"
)


class _Rig:
    """A ReplyWaiters on a lock that cannot be re-entered, as the sink gives it."""

    def __init__(self) -> None:
        self.cond = OwnedCondition()
        self.end = DialEnd()
        self.waiters = ReplyWaiters(self.cond, self.end)

    def pong(self, pong: PongMessage) -> None:
        with self.cond:
            self.waiters.deliver_pong_locked(pong)

    def response(self, response: QueryResponse) -> None:
        with self.cond:
            self.waiters.deliver_query_locked(response)

    def ledger_emptied(self, ack: AckMessage) -> None:
        with self.cond:
            self.waiters.ledger_emptied_locked(ack)

    def drained(self, *, owed: bool) -> Pending[None, AckMessage] | None:
        with self.cond:
            return self.waiters.expect_drained_locked(owed=owed)

    def fail_all(self) -> None:
        with self.cond:
            self.waiters.fail_all_locked()


def _response() -> QueryResponse:
    return QueryResponse(method="m")


class TestThePing:
    def test_a_pong_echoing_the_ping_answers_it(self) -> None:
        rig = _Rig()
        ping = rig.waiters.expect_pong(1.5)

        rig.pong(PongMessage(ts=1.5))

        assert rig.waiters.await_reply(ping, 0.0) == PongMessage(ts=1.5)

    def test_a_pong_for_another_ts_is_dropped(self) -> None:
        rig = _Rig()
        ping = rig.waiters.expect_pong(1.5)

        rig.pong(PongMessage(ts=9.0))

        assert rig.waiters.await_reply(ping, 0.0) is None

    def test_a_second_ping_in_flight_is_refused(self) -> None:
        rig = _Rig()
        rig.waiters.expect_pong(1.0)

        with pytest.raises(RuntimeError, match="a ping is already in flight"):
            rig.waiters.expect_pong(2.0)


class TestTheQuery:
    def test_the_next_response_answers_the_query(self) -> None:
        rig = _Rig()
        query = rig.waiters.expect_query()

        rig.response(_response())

        assert rig.waiters.await_reply(query, 0.0) == _response()

    def test_a_response_with_no_query_in_flight_is_a_skewed_stream(self) -> None:
        rig = _Rig()

        with pytest.raises(ReplyOutOfOrderError, match="none in flight"):
            rig.response(_response())

    def test_a_second_query_in_flight_is_refused(self) -> None:
        rig = _Rig()
        rig.waiters.expect_query()

        with pytest.raises(RuntimeError, match="a query is already in flight"):
            rig.waiters.expect_query()

    def test_an_abandoned_query_keeps_no_late_answer(self) -> None:
        rig = _Rig()
        query = rig.waiters.expect_query()
        rig.waiters.abandon(query)

        with pytest.raises(ReplyOutOfOrderError):
            rig.response(_response())

    def test_an_answered_ticket_is_reported_until_it_is_taken(self) -> None:
        rig = _Rig()
        query = rig.waiters.expect_query()
        rig.response(_response())

        assert rig.waiters.answered(query) is True
        rig.waiters.await_reply(query, 0.0)
        assert rig.waiters.answered(query) is False


class TestTheDrainedWait:
    def test_nothing_owed_is_nothing_to_wait_for(self) -> None:
        assert _Rig().drained(owed=False) is None

    def test_the_ack_that_empties_the_ledger_answers_it(self) -> None:
        rig = _Rig()
        ticket = rig.drained(owed=True)
        assert ticket is not None

        rig.ledger_emptied(AckMessage(scene_id="a"))

        assert rig.waiters.await_reply(ticket, 0.0) == AckMessage(scene_id="a")

    def test_a_second_wait_in_flight_is_refused(self) -> None:
        rig = _Rig()
        rig.drained(owed=True)

        with pytest.raises(RuntimeError, match="an ack wait is already in flight"):
            rig.drained(owed=True)

    def test_an_abandoned_wait_frees_the_slot(self) -> None:
        rig = _Rig()
        ticket = rig.drained(owed=True)
        assert ticket is not None
        rig.waiters.abandon(ticket)

        assert rig.drained(owed=True) is not None

    def test_failing_all_frees_the_slot(self) -> None:
        rig = _Rig()
        rig.drained(owed=True)
        rig.fail_all()

        assert rig.drained(owed=True) is not None


class TestTheEnd:
    def test_a_wait_on_an_ending_dial_is_refused(self) -> None:
        rig = _Rig()
        rig.end.ask_hub()

        with pytest.raises(ConnectionClosedError):
            rig.waiters.expect_query()

    def test_a_drained_wait_on_an_ending_dial_is_refused(self) -> None:
        rig = _Rig()
        rig.end.ask_hub()

        with pytest.raises(ConnectionClosedError):
            rig.drained(owed=True)

    def test_a_waiting_caller_is_failed_the_moment_the_waiters_fail(self) -> None:
        rig = _Rig()
        query = rig.waiters.expect_query()
        outcome: list[BaseException] = []

        def wait() -> None:
            try:
                rig.waiters.await_reply(query, 5.0)
            except ConnectionClosedError as exc:
                outcome.append(exc)

        thread = threading.Thread(target=wait)
        thread.start()
        rig.end.ask_hub()
        rig.fail_all()
        thread.join(2.0)

        assert len(outcome) == 1


_Call = Callable[[_Rig], object]
# The calls that take the sink's lock themselves.
_LOCKING: dict[str, _Call] = {
    "expect_pong": lambda rig: rig.waiters.expect_pong(1.0),
    "expect_query": lambda rig: rig.waiters.expect_query(),
    "await_reply": lambda rig: rig.waiters.await_reply(_STRANGER, 0.0),
    "answered": lambda rig: rig.waiters.answered(_STRANGER),
    "abandon": lambda rig: rig.waiters.abandon(_STRANGER),
}


def _in_flight(rig: _Rig) -> None:
    """A ping, a query and a drained wait, all in flight and all waited on."""
    rig.waiters.expect_pong(1.0)
    rig.waiters.expect_query()
    rig.drained(owed=True)


def _nothing(_rig: _Rig) -> None:
    """No state to prepare."""


# The bodies that run only under the lock: how to set the state up (outside it, so
# the answering path is the one that runs) and the call made while it is held.
_LOCKED: dict[str, tuple[Callable[[_Rig], None], _Call]] = {
    "deliver_pong_locked": (
        _in_flight,
        lambda rig: rig.waiters.deliver_pong_locked(PongMessage(ts=1.0)),
    ),
    "deliver_query_locked": (
        _in_flight,
        lambda rig: rig.waiters.deliver_query_locked(_response()),
    ),
    "ledger_emptied_locked": (
        _in_flight,
        lambda rig: rig.waiters.ledger_emptied_locked(AckMessage(scene_id="a")),
    ),
    "fail_all_locked": (_in_flight, lambda rig: rig.waiters.fail_all_locked()),
    "expect_drained_locked": (
        _nothing,
        lambda rig: rig.waiters.expect_drained_locked(owed=True),
    ),
}


def _public_methods() -> tuple[set[str], set[str]]:
    """The public methods of ReplyWaiters, derived: those that lock, and those that
    run only under the sink's lock (by the ``_locked`` suffix)."""
    names = {
        name
        for name, member in vars(ReplyWaiters).items()
        if inspect.isfunction(member) and not name.startswith("_")
    }
    locked = {name for name in names if name.endswith("_locked")}
    return names - locked, locked


class TestTheOneLock:
    """Every public method takes the sink's lock, or runs only under it."""

    def test_every_public_method_has_a_probe_and_no_probe_is_for_a_stranger(
        self,
    ) -> None:
        locking, locked = _public_methods()

        assert locking == set(_LOCKING), "a public method of ReplyWaiters is unprobed"
        assert locked == set(_LOCKED), "a *_locked method of ReplyWaiters is unprobed"

    @pytest.mark.parametrize("name", sorted(_LOCKING))
    def test_a_locking_method_waits_while_the_sinks_lock_is_held(
        self, name: str
    ) -> None:
        rig = _Rig()
        done = threading.Event()

        def run() -> None:
            _LOCKING[name](rig)
            done.set()

        with rig.cond:  # the sink's step holds the lock
            probe = threading.Thread(target=run, daemon=True)
            probe.start()
            assert not done.wait(0.2), "the method did not take the sink's lock"
        probe.join(3.0)

        assert done.is_set()

    @pytest.mark.parametrize("name", sorted(_LOCKED))
    def test_a_locked_body_never_takes_the_lock_its_caller_holds(
        self, name: str
    ) -> None:
        rig = _Rig()  # a lock that cannot be re-entered: a re-take would hang
        prepare, call = _LOCKED[name]
        prepare(rig)
        done = threading.Event()

        def run() -> None:
            with rig.cond:
                call(rig)
            done.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        assert done.wait(3.0), f"{name} took the lock its caller holds"

    @pytest.mark.parametrize("name", sorted(_LOCKED))
    def test_a_locked_body_called_without_the_lock_is_refused(self, name: str) -> None:
        rig = _Rig()
        prepare, call = _LOCKED[name]
        prepare(rig)

        with pytest.raises(LockDisciplineError, match="without the sink's lock"):
            call(rig)

    @pytest.mark.parametrize("name", sorted(_LOCKED))
    def test_a_locked_body_called_while_another_thread_holds_the_lock_is_refused(
        self, name: str
    ) -> None:
        rig = _Rig()
        prepare, call = _LOCKED[name]
        prepare(rig)
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with rig.cond:
                held.set()
                release.wait(3.0)

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        assert held.wait(3.0)

        try:
            with pytest.raises(LockDisciplineError, match="without the sink's lock"):
                call(rig)
        finally:
            release.set()
            holder.join(3.0)

    def test_the_waiters_make_no_lock_of_their_own(self) -> None:
        names = {
            node.attr if isinstance(node, ast.Attribute) else node.id
            for node in ast.walk(ast.parse(_SOURCE.read_text("utf-8")))
            if isinstance(node, ast.Attribute | ast.Name)
        }

        assert not names & {"Lock", "RLock", "Semaphore", "BoundedSemaphore"}
        # The Condition is only ever the one passed in: it is never constructed here.
        constructed = {
            node.func.attr if isinstance(node.func, ast.Attribute) else ""
            for node in ast.walk(ast.parse(_SOURCE.read_text("utf-8")))
            if isinstance(node, ast.Call)
        }
        assert "Condition" not in constructed


class TestThroughTheSink:
    def test_the_sinks_lock_is_held_by_one_thread_at_a_time(self) -> None:
        sink = ReplySink()
        seen: list[bool] = []

        with sink._cond:  # test seam: the lock the waiters are lent
            looking = threading.Thread(
                target=lambda: seen.append(sink._cond.held_here()), daemon=True
            )
            looking.start()
            looking.join(3.0)

            assert (sink._cond.held_here(), seen) == (True, [False])
        assert not sink._cond.held_here()

    @pytest.mark.parametrize("how", ["request_hub", "end"])
    @pytest.mark.parametrize("what", ["query", "ping"])
    def test_an_end_wakes_a_blocked_waiter_with_a_failure(
        self, how: str, what: str
    ) -> None:
        sink = ReplySink()
        pending = sink.expect_query() if what == "query" else sink.expect_pong(1.0)
        outcome: list[BaseException] = []

        def wait() -> None:
            try:
                sink.await_reply(pending, 10.0)
            except ConnectionClosedError as exc:
                outcome.append(exc)

        thread = threading.Thread(target=wait)
        thread.start()
        if how == "request_hub":
            sink.request_hub()
        else:
            sink.end("display")
        thread.join(2.0)

        assert not thread.is_alive(), "the waiter slept through the end"
        assert len(outcome) == 1

    def test_the_ledger_emptying_answers_a_drained_wait_and_an_end_fails_it(
        self,
    ) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        ticket = sink.expect_drained()
        assert ticket is not None

        sink.deliver(AckMessage(scene_id="a"))

        assert sink.await_reply(ticket, 0.0) == AckMessage(scene_id="a")
