"""PropertyObservers -- who hears a property change, and who hears a restore."""

from __future__ import annotations

import logging
from typing import Self

import pytest

from punt_lux.domain.handler_writes import WriteRefusedError
from punt_lux.domain.observer_state import ObserverCheckpoint
from punt_lux.domain.programmer_error import ProgrammerError
from punt_lux.domain.property_observers import PropertyObservers


def _heard() -> tuple[PropertyObservers, list[str]]:
    observers = PropertyObservers()
    heard: list[str] = []
    observers.add(heard.append)
    return observers, heard


class TestAnnouncing:
    def test_an_observer_hears_each_property_once_in_first_seen_order(self) -> None:
        observers, heard = _heard()

        observers.announce(["rows", "selected", "rows"], "e")

        assert heard == ["rows", "selected"]

    def test_observers_hear_in_the_order_they_registered(self) -> None:
        observers = PropertyObservers()
        order: list[str] = []
        observers.add(lambda _prop: order.append("first"))
        observers.add(lambda _prop: order.append("second"))

        observers.announce(["rows"], "e")

        assert order == ["first", "second"]


class TestAFailingObserver:
    def test_it_is_logged_for_what_it_was_and_the_others_still_hear(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        observers, heard = _heard()

        def broken(_prop: str) -> None:
            msg = "the observer's own bug"
            raise RuntimeError(msg)

        observers.add(broken)
        observers.add(heard.append)

        with caplog.at_level(logging.ERROR):
            observers.announce(["rows"], "e")

        assert heard == ["rows", "rows"]
        assert "failed on 'rows' of element e" in caplog.text

    def test_a_refused_write_is_raised_after_the_others_have_heard(self) -> None:
        observers, heard = _heard()

        def refusing(_prop: str) -> None:
            raise WriteRefusedError

        observers.add(refusing)
        observers.add(heard.append)

        with pytest.raises(WriteRefusedError):
            observers.announce(["rows"], "e")

        assert heard == ["rows", "rows"]

    def test_announcing_goes_on_past_a_refusal_and_raises_the_first(self) -> None:
        observers, heard = _heard()
        first = WriteRefusedError("first")

        def refusing(prop: str) -> None:
            raise first if prop == "a" else WriteRefusedError(prop)

        observers.add(refusing)

        with pytest.raises(WriteRefusedError) as raised:
            observers.announce(["a", "b"], "e")

        assert raised.value is first
        assert heard == ["a", "b"]

    def test_a_programmer_error_is_never_swallowed(self) -> None:
        observers = PropertyObservers()

        def breaks_a_rule(_prop: str) -> None:
            raise ProgrammerError("a rule the code keeps")

        observers.add(breaks_a_rule)

        with pytest.raises(ProgrammerError):
            observers.announce(["rows"], "e")


class _Nothing:
    def restore(self) -> None:
        """Restore nothing: only the registration is under test."""


class _KeepsState:
    """A stateful observer: it carries its own callback and its own checkpoint."""

    _told: list[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._told = []
        return self

    @property
    def told(self) -> list[str]:
        return self._told

    def on_change(self, prop: str) -> None:
        self._told.append(prop)

    def checkpoint(self) -> ObserverCheckpoint:
        return _Nothing()


class TestAStatefulObserver:
    def test_it_hears_a_change_like_any_other(self) -> None:
        observers = PropertyObservers()
        keeper = _KeepsState()
        observers.add_stateful(keeper)

        observers.announce(["rows"], "e")

        assert keeper.told == ["rows"]

    def test_it_is_not_told_what_a_rollback_restored(self) -> None:
        observers, heard = _heard()
        keeper = _KeepsState()
        observers.add_stateful(keeper)

        observers.announce(["rows"], "e", restored=True)

        assert (heard, keeper.told) == (["rows"], [])

    def test_its_checkpoint_is_taken_with_the_others(self) -> None:
        observers, _ = _heard()
        observers.add_stateful(_KeepsState())

        checkpoint = observers.checkpoint()

        checkpoint.restore()  # restores what it holds: one stand-in, no error
