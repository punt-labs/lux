"""A rule the code broke passes through every fan-out; it is never logged and dropped.

The structural guard (``tests/test_broad_catches_reraise_programmer_error.py``) proves
every broad catch in ``src`` re-raises or stands behind a ``ProgrammerError`` clause.
These tests plant a real one at the boundaries the review named and watch it arrive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.finally_guard import FinallyGuard
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.liveness import DisplayLiveness
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.domain.programmer_error import ProgrammerError
from punt_lux.protocol.elements import TableElement

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.keepalive_ports import KeepaliveConnection
    from punt_lux.protocol.messages.observer import ObserverMessage

_TOPIC = Topic("t")


def _breaks_a_rule(*_args: object) -> None:
    raise LockDisciplineError("planted: a lock taken in the wrong order")


def _breaking_writer(_message: ObserverMessage) -> bool:
    raise LockDisciplineError("planted: a writer that breaks a rule")


class TestTheObserverFanOut:
    def test_an_observer_that_breaks_a_rule_is_not_swallowed_by_a_patch(self) -> None:
        tree = TableElement(id="t", columns=["c"], rows=[["r"]])
        tree.add_observer(_breaks_a_rule)

        with pytest.raises(LockDisciplineError):
            tree.apply_patch({"rows": [["s"]]})

    def test_it_is_not_swallowed_by_a_removal(self) -> None:
        tree = TableElement(id="t", columns=["c"], rows=[["r"]])
        tree.add_observer(_breaks_a_rule)

        with pytest.raises(LockDisciplineError):
            tree.mark_removed()

    def test_an_ordinary_failure_still_costs_only_its_own_observer(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        tree = TableElement(id="t", columns=["c"], rows=[["r"]])
        heard: list[str] = []

        def fails(_prop: str) -> None:
            raise ValueError("an observer's own bug")

        tree.add_observer(fails)
        tree.add_observer(heard.append)

        with caplog.at_level(logging.ERROR):
            tree.apply_patch({"rows": [["s"]]})

        assert heard == ["rows"]


class TestHubPublish:
    def test_a_subscriber_that_breaks_a_rule_is_not_swallowed(self) -> None:
        hub = Hub()
        conn = ConnectionId("c")
        hub.register_writer(conn, _breaking_writer)
        hub.subscribe(conn, _TOPIC)

        with pytest.raises(LockDisciplineError):
            hub.publish(conn, _TOPIC, {})


class TestTheFinallyGuard:
    def test_an_action_that_breaks_a_rule_surfaces_even_when_the_body_failed(
        self,
    ) -> None:
        def action() -> None:
            raise LockDisciplineError("planted in the action")

        with pytest.raises(LockDisciplineError) as caught, FinallyGuard(action, "x"):
            raise KeyError("the body's own failure")

        assert isinstance(caught.value, ProgrammerError)
        assert isinstance(caught.value.__cause__, KeyError)

    def test_an_ordinary_action_failure_is_logged_and_the_body_failure_stands(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def action() -> None:
            raise ValueError("the action's own failure")

        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(KeyError),
            FinallyGuard(action, "x"),
        ):
            raise KeyError("the body's own failure")

        assert "the action's own failure" in caplog.text or "x failed" in caplog.text


class _Clients:
    """Keepalive clients whose connection breaks a rule when asked for a probe."""

    def asks(self) -> KeepaliveConnection:
        raise LockDisciplineError("planted in the liveness cycle")

    def drop_unresponsive(self, dial: DialRef) -> None:  # pragma: no cover
        raise AssertionError(dial)


class TestTheLivenessLoop:
    def test_a_cycle_that_breaks_a_rule_ends_the_loop(self) -> None:
        worker = DisplayLiveness(_Clients(), interval=0.01)

        with pytest.raises(LockDisciplineError):
            worker._run()
