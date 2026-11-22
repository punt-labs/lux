"""RespawnBackoff — the respawn delay's growth and its serve-stably reset.

Distinct from the replicator's send-retry backoff on purpose (see the module
docstring): this backoff grows on every respawn and resets only after a
stable interval with no further respawn, never on a clean send.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.hub.backoff_config import BackoffConfig
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
    backoff = RespawnBackoff(BackoffConfig(clock=_FakeClock()))
    assert backoff.note_respawn() == 1.0


def test_successive_respawns_double_up_to_the_cap() -> None:
    backoff = RespawnBackoff(BackoffConfig(clock=_FakeClock()))
    delays = [backoff.note_respawn() for _ in range(8)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_reset_if_stable_does_nothing_before_a_respawn() -> None:
    backoff = RespawnBackoff(BackoffConfig(clock=_FakeClock()))
    assert backoff.reset_if_stable() is False


def test_reset_if_stable_waits_for_the_full_interval() -> None:
    clock = _FakeClock()
    backoff = RespawnBackoff(BackoffConfig(clock=clock))
    backoff.note_respawn()
    backoff.note_respawn()  # delay now 2.0
    clock.advance(STABLE_INTERVAL - 1.0)
    assert backoff.reset_if_stable() is False
    assert backoff.note_respawn() == 4.0  # still growing from where it left off


def test_reset_if_stable_resets_the_delay_after_the_interval() -> None:
    clock = _FakeClock()
    backoff = RespawnBackoff(BackoffConfig(clock=clock))
    backoff.note_respawn()
    backoff.note_respawn()  # delay now 2.0
    clock.advance(STABLE_INTERVAL)
    assert backoff.reset_if_stable() is True
    assert backoff.note_respawn() == 1.0  # back to base


def test_a_respawn_during_the_interval_restarts_it() -> None:
    # A display that keeps dying keeps its backoff climbing — the reset
    # measures time since the *last* respawn, not the first.
    clock = _FakeClock()
    backoff = RespawnBackoff(BackoffConfig(clock=clock))
    backoff.note_respawn()
    clock.advance(STABLE_INTERVAL - 1.0)
    backoff.note_respawn()  # restarts the interval; delay now 2.0
    clock.advance(2.0)
    assert backoff.reset_if_stable() is False
    assert backoff.note_respawn() == 4.0


def test_current_delay_reflects_the_pending_delay_without_mutating_it() -> None:
    backoff = RespawnBackoff(BackoffConfig(clock=_FakeClock()))
    assert backoff.current_delay == 1.0
    assert backoff.current_delay == 1.0  # a second read is unchanged
    backoff.note_respawn()
    assert backoff.current_delay == 2.0  # reflects the grown delay


def test_a_parameterized_instance_paces_within_its_own_bounds() -> None:
    # The disconnected-display backoff's shape (design §6.2): base 2s, cap
    # 120s, independent of the crash-respawn default (1s -> 30s).
    clock = _FakeClock()
    backoff = RespawnBackoff(
        BackoffConfig(clock=clock, base_delay=2.0, max_delay=120.0)
    )
    delays = [backoff.note_respawn() for _ in range(7)]
    assert delays == [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 120.0]


def test_a_parameterized_instance_resets_to_its_own_base() -> None:
    clock = _FakeClock()
    backoff = RespawnBackoff(
        BackoffConfig(clock=clock, base_delay=2.0, max_delay=120.0)
    )
    backoff.note_respawn()
    backoff.note_respawn()  # delay now 8.0
    clock.advance(STABLE_INTERVAL)
    assert backoff.reset_if_stable() is True
    assert backoff.current_delay == 2.0  # its own base, not the module default
