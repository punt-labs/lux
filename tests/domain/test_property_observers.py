"""PropertyObservers -- who hears a property change, buffered while a patch runs."""

from __future__ import annotations

import logging

import pytest

from punt_lux.domain.handler_writes import WriteRefusedError
from punt_lux.domain.property_observers import PropertyObservers


def _heard() -> tuple[PropertyObservers, list[str]]:
    observers = PropertyObservers()
    heard: list[str] = []
    observers.add(heard.append)
    return observers, heard


class TestBuffering:
    def test_outside_a_patch_an_observer_hears_at_once(self) -> None:
        observers, heard = _heard()

        observers.notify("rows", "e")

        assert heard == ["rows"]

    def test_inside_a_patch_nobody_hears_until_it_commits(self) -> None:
        observers, heard = _heard()
        observers.begin()

        observers.notify("rows", "e")
        assert heard == []
        observers.commit("e")

        assert heard == ["rows"]

    def test_each_property_is_heard_once_in_first_seen_order(self) -> None:
        observers, heard = _heard()
        observers.begin()

        for prop in ("rows", "selected", "rows"):
            observers.notify(prop, "e")
        observers.commit("e")

        assert heard == ["rows", "selected"]

    def test_a_failed_patch_tells_nobody(self) -> None:
        observers, heard = _heard()
        observers.begin()
        observers.notify("rows", "e")

        observers.discard()
        observers.notify("label", "e")  # outside a patch again: heard at once

        assert heard == ["label"]


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
            observers.notify("rows", "e")

        assert heard == ["rows", "rows"]
        assert "failed on 'rows' of element e" in caplog.text

    def test_a_refused_write_is_raised_after_the_others_have_heard(self) -> None:
        observers, heard = _heard()

        def refusing(_prop: str) -> None:
            raise WriteRefusedError

        observers.add(refusing)
        observers.add(heard.append)

        with pytest.raises(WriteRefusedError):
            observers.notify("rows", "e")

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
