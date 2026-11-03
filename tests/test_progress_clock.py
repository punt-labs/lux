"""ProgressClock: a window that every moved byte restarts."""

from __future__ import annotations

import pytest

from punt_lux.progress_clock import ProgressClock


class _Time:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock_time(monkeypatch: pytest.MonkeyPatch) -> _Time:
    fake = _Time()
    monkeypatch.setattr("punt_lux.progress_clock.time.monotonic", fake)
    return fake


def test_a_new_clock_counts_its_making_as_progress(clock_time: _Time) -> None:
    clock = ProgressClock()

    assert (clock.expires_at(5.0), clock.progressed_within(5.0)) == (105.0, True)


def test_the_window_closes_once_it_has_passed_with_no_byte(clock_time: _Time) -> None:
    clock = ProgressClock()
    clock_time.now += 5.0

    assert clock.progressed_within(5.0) is False


def test_the_window_is_still_open_just_before_it_closes(clock_time: _Time) -> None:
    clock = ProgressClock()
    clock_time.now += 4.999

    assert clock.progressed_within(5.0) is True


def test_a_moved_byte_restarts_the_window(clock_time: _Time) -> None:
    clock = ProgressClock()
    clock_time.now += 4.0
    clock.moved()
    clock_time.now += 4.0

    assert (clock.expires_at(5.0), clock.progressed_within(5.0)) == (109.0, True)


def test_a_zero_window_is_never_open(clock_time: _Time) -> None:
    assert ProgressClock().progressed_within(0.0) is False
