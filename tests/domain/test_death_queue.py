"""DeathQueue -- deaths wait oldest first, are taken once, and a taken one can go back."""

from __future__ import annotations

import logging

import pytest

from punt_lux.domain.hub.death_queue import DeathQueue
from punt_lux.domain.hub.dial_death import DialDeath
from punt_lux.domain.ids import SceneId


def _death(name: str) -> DialDeath:
    return DialDeath(frozenset({SceneId(name)}), "pair-1", "display")


class TestTheOrderDeathsComeOut:
    def test_they_come_out_oldest_first_and_each_once(self) -> None:
        queue = DeathQueue()
        queue.queue(_death("a"))
        queue.queue(_death("b"))

        assert [queue.take(), queue.take(), queue.take()] == [
            _death("a"),
            _death("b"),
            None,
        ]

    def test_a_death_put_back_is_the_next_one_taken(self) -> None:
        queue = DeathQueue()
        queue.queue(_death("a"))
        queue.queue(_death("b"))
        first = queue.take()
        assert first is not None

        queue.put_back(first)

        assert [queue.take(), queue.take()] == [_death("a"), _death("b")]

    def test_a_death_queued_while_another_is_out_still_comes_after_it(self) -> None:
        queue = DeathQueue()
        queue.queue(_death("a"))
        taken = queue.take()
        assert taken is not None
        queue.queue(_death("b"))

        queue.put_back(taken)

        assert [queue.take(), queue.take()] == [_death("a"), _death("b")]


class TestAQueueThatGrows:
    def test_past_the_warning_mark_every_death_is_kept_and_it_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        queue = DeathQueue()

        with caplog.at_level(logging.WARNING):
            for turn in range(70):
                queue.queue(_death(f"s{turn}"))

        kept = []
        while (death := queue.take()) is not None:
            kept.append(death)
        assert len(kept) == 70
        assert "wait to be charged" in caplog.text
