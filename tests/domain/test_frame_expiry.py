"""FrameExpiry arms, refreshes, and claims frame deadlines on a controllable clock.

The deadlines run on an injected monotonic clock so time is a value the test sets,
not a wall the test waits on. These cases pin the behaviour the Hub relies on: a
frame with no TTL never becomes due, a TTL becomes due once the clock passes it, a
re-show replaces or clears the deadline, and ``due_frames`` reports the due set
without consuming it (the caller disarms after a successful tear-down).
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.frame_expiry import FrameExpiry


@final
class FakeClock:
    """A settable monotonic clock: the test moves time by assigning ``now``."""

    _now: float
    __slots__ = ("_now",)

    def __new__(cls, start: float = 0.0) -> Self:
        self = super().__new__(cls)
        self._now = start
        return self

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward by ``seconds``."""
        self._now += seconds


def test_unarmed_frame_is_never_due() -> None:
    expiry = FrameExpiry(FakeClock())
    assert expiry.due_frames() == frozenset()
    assert expiry.seconds_until_next() is None


def test_armed_frame_becomes_due_only_after_its_deadline() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("f", 5.0)

    clock.advance(4.9)
    assert expiry.due_frames() == frozenset()

    clock.advance(0.1)
    assert expiry.due_frames() == frozenset({"f"})


def test_due_frames_is_a_peek_until_disarmed() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("f", 1.0)
    clock.advance(1.0)

    assert expiry.due_frames() == frozenset({"f"})
    assert expiry.due_frames() == frozenset({"f"})  # not consumed by the peek

    expiry.disarm("f")
    assert expiry.due_frames() == frozenset()  # only disarm removes it


def test_due_frames_takes_only_the_frames_that_are_due() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("soon", 1.0)
    expiry.arm("later", 10.0)
    clock.advance(1.0)

    assert expiry.due_frames() == frozenset({"soon"})  # later is not yet due


def test_reshow_with_new_ttl_replaces_the_deadline() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("f", 1.0)

    expiry.set_deadline("f", 10.0)  # re-show before the first deadline passes
    clock.advance(1.0)
    assert expiry.due_frames() == frozenset()

    clock.advance(9.0)
    assert expiry.due_frames() == frozenset({"f"})


def test_reshow_without_ttl_makes_the_frame_permanent() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("f", 1.0)

    expiry.set_deadline("f", None)  # re-show without a TTL
    clock.advance(100.0)
    assert expiry.due_frames() == frozenset()
    assert expiry.seconds_until_next() is None


def test_disarm_is_idempotent() -> None:
    expiry = FrameExpiry(FakeClock())
    expiry.disarm("never-armed")  # no raise
    expiry.arm("f", 1.0)
    expiry.disarm("f")
    expiry.disarm("f")
    assert expiry.seconds_until_next() is None


def test_seconds_until_next_clamps_a_passed_deadline_to_zero() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("f", 1.0)
    clock.advance(5.0)
    assert expiry.seconds_until_next() == 0.0


def test_seconds_until_next_reports_the_soonest_deadline() -> None:
    clock = FakeClock()
    expiry = FrameExpiry(clock)
    expiry.arm("a", 3.0)
    expiry.arm("b", 1.0)
    expiry.arm("c", 8.0)
    assert expiry.seconds_until_next() == 1.0
