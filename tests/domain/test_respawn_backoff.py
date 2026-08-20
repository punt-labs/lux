"""RespawnBackoff — the respawn delay's growth and its serve-stably reset.

Distinct from the replicator's send-retry backoff on purpose (see the module
docstring): this backoff grows on every respawn and resets only after a
stable interval with no further respawn, never on a clean send.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.hub.crash_attribution import STABLE_INTERVAL
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff


class _FakeClock:
    """A settable clock: tests advance time explicitly, deterministically."""

    _now: float
    __slots__ = ("_now",)

    def __new__(cls, start: float = 0.0) -> Self:
        self = super().__new__(cls)
        self._now = start
        return self

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_the_first_respawn_delay_is_the_base() -> None:
    backoff = RespawnBackoff(_FakeClock())
    assert backoff.note_respawn() == 1.0


def test_successive_respawns_double_up_to_the_cap() -> None:
    backoff = RespawnBackoff(_FakeClock())
    delays = [backoff.note_respawn() for _ in range(8)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_reset_if_stable_does_nothing_before_a_respawn() -> None:
    backoff = RespawnBackoff(_FakeClock())
    assert backoff.reset_if_stable() is False


def test_reset_if_stable_waits_for_the_full_interval() -> None:
    clock = _FakeClock()
    backoff = RespawnBackoff(clock)
    backoff.note_respawn()
    backoff.note_respawn()  # delay now 2.0
    clock.advance(STABLE_INTERVAL - 1.0)
    assert backoff.reset_if_stable() is False
    assert backoff.note_respawn() == 4.0  # still growing from where it left off


def test_reset_if_stable_resets_the_delay_after_the_interval() -> None:
    clock = _FakeClock()
    backoff = RespawnBackoff(clock)
    backoff.note_respawn()
    backoff.note_respawn()  # delay now 2.0
    clock.advance(STABLE_INTERVAL)
    assert backoff.reset_if_stable() is True
    assert backoff.note_respawn() == 1.0  # back to base


def test_a_respawn_during_the_interval_restarts_it() -> None:
    # A display that keeps dying keeps its backoff climbing — the reset
    # measures time since the *last* respawn, not the first.
    clock = _FakeClock()
    backoff = RespawnBackoff(clock)
    backoff.note_respawn()
    clock.advance(STABLE_INTERVAL - 1.0)
    backoff.note_respawn()  # restarts the interval; delay now 2.0
    clock.advance(2.0)
    assert backoff.reset_if_stable() is False
    assert backoff.note_respawn() == 4.0
