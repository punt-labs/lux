"""CrashAttribution — the windowed death tally, mode transitions, and exit.

Drives the object directly against a fake port and a controllable clock, so
each partition of display-crash-quarantine.md Question 1 is a deterministic
unit test: batching's whole-batch attribution and mode switch, isolation's
singleton attribution, the threshold quarantine, the window's age-out, and
the stable-interval isolation exit (never on one clean pass).
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.hub.crash_attribution import (
    ATTRIBUTION_THRESHOLD,
    ATTRIBUTION_WINDOW,
    STABLE_INTERVAL,
    CrashAttribution,
)
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.ids import SceneId

_A = SceneId("a")
_B = SceneId("b")


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


class _FakePort:
    """Records every quarantine call and answers is_quarantined from them.

    Also records observer registrations so tests can assert that
    :class:`CrashAttribution` wires up ``clear_tally`` on construction.
    """

    records: dict[SceneId, QuarantineRecord]
    observers: list[object]
    __slots__ = ("observers", "records")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.records = {}
        self.observers = []
        return self

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        self.records[scene_id] = record

    def is_quarantined(self, scene_id: SceneId) -> bool:
        return scene_id in self.records

    def add_quarantine_cleared_observer(self, observer: object) -> None:
        self.observers.append(observer)


def test_constants_match_the_design() -> None:
    # Named exactly, per the design contract, so the policy is one place to
    # read and to tune.
    assert ATTRIBUTION_THRESHOLD == 2
    assert ATTRIBUTION_WINDOW == 60.0
    assert STABLE_INTERVAL == 60.0
    assert STABLE_INTERVAL >= ATTRIBUTION_WINDOW


def test_starts_in_batching_mode() -> None:
    attribution = CrashAttribution(_FakePort(), _FakeClock())
    assert attribution.mode == "batching"


def test_a_death_switches_to_isolating_mode() -> None:
    attribution = CrashAttribution(_FakePort(), _FakeClock())
    attribution.attribute_death(frozenset({_A}))
    assert attribution.mode == "isolating"


def test_one_death_does_not_quarantine() -> None:
    # THRESHOLD is 2: a single death admits a non-scene cause and must not
    # quarantine a scene on its own.
    port = _FakePort()
    attribution = CrashAttribution(port, _FakeClock())
    newly = attribution.attribute_death(frozenset({_A}))
    assert newly == frozenset()
    assert not attribution.is_quarantined(_A)


def test_two_deaths_within_the_window_quarantine() -> None:
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A}))
    clock.advance(1.0)
    newly = attribution.attribute_death(frozenset({_A}))
    assert newly == frozenset({_A})
    assert attribution.is_quarantined(_A)
    assert port.records[_A].death_count == 2


def test_a_batched_death_attributes_every_scene_in_the_batch() -> None:
    # A batching-mode death is correlational: the whole batch is suspect,
    # because a socket-level send failure cannot tell which scene crashed
    # the renderer.
    attribution = CrashAttribution(_FakePort(), _FakeClock())
    attribution.attribute_death(frozenset({_A, _B}))
    attribution.attribute_death(frozenset({_A, _B}))
    assert attribution.is_quarantined(_A)
    assert attribution.is_quarantined(_B)


def test_a_death_outside_the_window_does_not_accumulate_with_an_old_one() -> None:
    # The window is the only decay: an old death ages out, so the second one
    # starts the tally over rather than reaching the threshold immediately.
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A}))
    clock.advance(ATTRIBUTION_WINDOW + 1.0)
    newly = attribution.attribute_death(frozenset({_A}))
    assert newly == frozenset()
    assert not attribution.is_quarantined(_A)


def test_quarantine_if_threshold_is_idempotent_below_threshold() -> None:
    attribution = CrashAttribution(_FakePort(), _FakeClock())
    assert attribution.quarantine_if_threshold(_A) is False


def test_exit_isolation_if_stable_does_nothing_in_batching_mode() -> None:
    attribution = CrashAttribution(_FakePort(), _FakeClock())
    assert attribution.exit_isolation_if_stable() is False
    assert attribution.mode == "batching"


def test_exit_isolation_if_stable_waits_for_the_full_interval() -> None:
    clock = _FakeClock()
    attribution = CrashAttribution(_FakePort(), clock)
    attribution.attribute_death(frozenset({_A}))
    clock.advance(STABLE_INTERVAL - 1.0)
    assert attribution.exit_isolation_if_stable() is False
    assert attribution.mode == "isolating"


def test_exit_isolation_if_stable_returns_to_batching_after_the_interval() -> None:
    clock = _FakeClock()
    attribution = CrashAttribution(_FakePort(), clock)
    attribution.attribute_death(frozenset({_A}))
    clock.advance(STABLE_INTERVAL)
    assert attribution.exit_isolation_if_stable() is True
    assert attribution.mode == "batching"


def test_a_death_during_isolation_restarts_the_stable_interval() -> None:
    # A death, of any scene, restarts the interval — the intermittent-crasher
    # guard the earlyexit fidelity control exists to prove is load-bearing.
    clock = _FakeClock()
    attribution = CrashAttribution(_FakePort(), clock)
    attribution.attribute_death(frozenset({_A}))
    clock.advance(STABLE_INTERVAL - 1.0)
    attribution.attribute_death(frozenset({_B}))  # restarts the interval
    clock.advance(2.0)  # short of a full interval since the restart
    assert attribution.exit_isolation_if_stable() is False
    assert attribution.mode == "isolating"


def test_is_quarantined_reflects_the_port_not_a_local_cache() -> None:
    # The port is the single source of truth: quarantine can also be lifted
    # by an owner's re-show, which this object never observes.
    port = _FakePort()
    attribution = CrashAttribution(port, _FakeClock())
    port.quarantine(_A, QuarantineRecord(death_count=2, last_death_at=0.0))
    assert attribution.is_quarantined(_A)
    port.records.clear()
    assert not attribution.is_quarantined(_A)


def test_clear_tally_drops_every_attributed_death_for_a_scene() -> None:
    # Finding 2's core: once quarantine is lifted, the tally must be gone too,
    # so a re-crashed scene needs the full threshold again — never re-quarantine
    # off a single fresh death while a stale in-window tally still sits at
    # THRESHOLD - 1.
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A}))  # tally: [t=0]
    attribution.clear_tally(_A)
    clock.advance(1.0)
    newly = attribution.attribute_death(frozenset({_A}))  # fresh tally: [t=1]
    assert newly == frozenset()  # would be {A} without the clear
    assert not attribution.is_quarantined(_A)


def test_clear_tally_leaves_other_scenes_intact() -> None:
    # The clear is scoped to one scene: another scene mid-way to the threshold
    # keeps its accrued deaths, so an unrelated recovery does not reset the
    # attribution across the whole store.
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A, _B}))  # both tallies: 1
    attribution.clear_tally(_A)
    clock.advance(1.0)
    newly = attribution.attribute_death(frozenset({_B}))  # B: 2 -> quarantined
    assert newly == frozenset({_B})


def test_clear_tally_is_a_noop_on_a_scene_that_never_crashed() -> None:
    attribution = CrashAttribution(_FakePort(), _FakeClock())
    attribution.clear_tally(_A)  # no exception, no state change
    assert attribution.mode == "batching"


def test_attribute_death_plumbs_the_render_error_onto_the_quarantine_record() -> None:
    # An agent whose scene later goes dark must see WHY, not just that. The
    # exception message the replicator caught at the failed send lands on the
    # record via attribute_death's render_error kwarg.
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A}), render_error="EPIPE from probe")
    clock.advance(1.0)
    attribution.attribute_death(frozenset({_A}), render_error="EPIPE from send")
    assert port.records[_A].render_error == "EPIPE from send"


def test_attribute_death_render_error_defaults_to_none() -> None:
    # Callers with no exception to attribute (a synthetic priming attribute in
    # tests, etc.) leave the field None — the honest default.
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A}))
    clock.advance(1.0)
    attribution.attribute_death(frozenset({_A}))
    assert port.records[_A].render_error is None


def test_exit_isolation_if_stable_clears_stale_tallies() -> None:
    # Finding E: on exit-to-batching every tally is already past
    # ATTRIBUTION_WINDOW (STABLE_INTERVAL >= ATTRIBUTION_WINDOW), so clearing
    # them is safe and keeps memory from growing without bound after a batched
    # death touched many scenes. White-box because this is a memory-hygiene
    # invariant, not a behavioural one.
    port = _FakePort()
    clock = _FakeClock()
    attribution = CrashAttribution(port, clock)
    attribution.attribute_death(frozenset({_A, _B}))  # both tally 1
    assert attribution._tallies  # test-only: proves state exists to clear
    clock.advance(STABLE_INTERVAL)
    assert attribution.exit_isolation_if_stable() is True
    assert attribution._tallies == {}
    assert attribution._last_death_at is None
