"""SendRecovery — reap/respawn vs reconnect, the consolidated re-mark, restore.

Unit-tests the recovery policy directly against fakes, complementing the
worker-level partitions in ``test_hub_replicator``: a wedged display is reaped
and respawned (K1/K2), a dead peer only reconnects (RC1), a consumed clear is
re-marked (RC4), a best-effort shutdown flush heals nothing (SH2), a failed batch
is restored intact (RR1), and the menu is re-marked unconditionally on the heal
path — so a display that came back blank gets the bar re-pushed even when the
failed batch carried no menu change, while ``restore`` re-marks the menu only
when the batch itself did. ``recover`` no longer enumerates live scenes itself
(DES-068 consolidation onto ``ClientRegistry._connect_and_reconcile``): these
tests verify it calls ``get()`` right after ``drop()`` — the one connect-success
hook — and re-queues only the failed batch's own scenes on top.

Also covers the crash-quarantine wiring (display-crash-quarantine.md): ``recover``
attributes the death to its caller-given ``suspect`` set through a real
``CrashAttribution`` before healing, and paces a wedged respawn through a real
``RespawnBackoff`` — both against a fake port and a settable clock, so pacing and
attribution are deterministic without a real sleep.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.hub.crash_attribution import CrashAttribution
from punt_lux.domain.hub.dirty_signal import DrainedBatch
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff
from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pytest

    from punt_lux.domain.hub.dirty_signal import DirtySignal
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle


class _FakeProvider:
    """Counts drops and gets, and the order they happen in."""

    drops: int
    gets: int
    calls: list[str]
    __slots__ = ("calls", "drops", "gets")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.drops = 0
        self.gets = 0
        self.calls = []
        return self

    def get(self) -> object:
        self.gets += 1
        self.calls.append("get")
        return self

    def drop(self) -> None:
        self.drops += 1
        self.calls.append("drop")


class _FakeLifecycle:
    """Records reap/ensure order."""

    calls: list[str]
    __slots__ = ("calls",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.calls = []
        return self

    def reap(self, timeout: float = 2.0) -> None:
        self.calls.append("reap")

    def ensure(self, timeout: float = 5.0) -> Path:
        self.calls.append("ensure")
        return Path("/tmp/lux-test.sock")


class _FakeSignal:
    """Records the re-marks a recovery makes."""

    menu_marks: int
    added: list[SceneId]
    __slots__ = ("added", "menu_marks")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.menu_marks = 0
        self.added = []
        return self

    def mark_menus(self) -> None:
        self.menu_marks += 1

    def add_all(self, scenes: Iterable[SceneId]) -> None:
        self.added.extend(scenes)


class _FakePort:
    """Records every quarantine call, for asserting attribution ran."""

    records: dict[SceneId, QuarantineRecord]
    __slots__ = ("records",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.records = {}
        return self

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        self.records[scene_id] = record

    def is_quarantined(self, scene_id: SceneId) -> bool:
        return scene_id in self.records


def _recovery() -> tuple[
    SendRecovery, _FakeProvider, _FakeLifecycle, _FakeSignal, CrashAttribution
]:
    provider = _FakeProvider()
    lifecycle = _FakeLifecycle()
    signal = _FakeSignal()
    attribution = CrashAttribution(_FakePort(), lambda: 0.0)
    recovery = SendRecovery(
        cast("ClientProvider", provider),
        cast("DisplayLifecycle", lifecycle),
        cast("DirtySignal", signal),
        attribution,
        RespawnBackoff(lambda: 0.0),
    )
    return recovery, provider, lifecycle, signal, attribution


_SCENE = SceneId("s1")
_BATCH = DrainedBatch(frozenset({_SCENE}), shutting=False)
_SHUTTING_BATCH = DrainedBatch(frozenset({_SCENE}), shutting=True)
_MENU_BATCH = DrainedBatch(frozenset({_SCENE}), shutting=False, menus_dirty=True)


def _no_sleep(_seconds: float) -> None:
    """A ``time.sleep`` stand-in that returns instantly, for deterministic tests."""


def test_a_wedged_display_is_reaped_then_respawned_then_remarked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("punt_lux.domain.hub.recovery.time.sleep", _no_sleep)
    recovery, provider, lifecycle, signal, _attribution = _recovery()
    recovery.recover(_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    assert lifecycle.calls == ["reap", "ensure"]  # kill before respawn
    assert provider.drops == 1
    assert signal.added == [_SCENE]  # the failed batch's own scenes re-marked


def test_a_dead_peer_reconnects_without_reaping() -> None:
    recovery, provider, lifecycle, signal, _attribution = _recovery()
    recovery.recover(_BATCH, wedged=False, suspect=frozenset({_SCENE}))
    assert lifecycle.calls == []  # nothing killed
    assert provider.drops == 1
    assert signal.added == [_SCENE]


def test_recover_calls_get_right_after_drop() -> None:
    """DES-068 consolidation: get() is the one connect-success hook.

    Calling it here (rather than waiting for the next send cycle) is what makes
    ``ClientRegistry._connect_and_reconcile`` the single place that declares the
    manifest and marks every live scene dirty on a fresh connect.
    """
    recovery, provider, _lifecycle, _signal, _attribution = _recovery()
    recovery.recover(_BATCH, wedged=False, suspect=frozenset({_SCENE}))
    assert provider.calls == ["drop", "get"]


def test_recovery_re_marks_the_menu_even_for_a_scene_only_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The headline fix at the recovery unit: a scene-only failure (the batch carried
    # no menu change) still re-marks the menu, so a display that came back blank gets
    # the agent bar re-pushed. The worker's fresh registry read at send time supplies
    # the current bar (or a harmless blank if none is set).
    monkeypatch.setattr("punt_lux.domain.hub.recovery.time.sleep", _no_sleep)
    recovery, _provider, _lifecycle, signal, _attribution = _recovery()
    recovery.recover(_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    assert signal.menu_marks == 1  # the menu is re-marked anyway
    assert signal.added == [_SCENE]


def test_a_shutdown_flush_heals_nothing() -> None:
    # SH2: a send that fails during the shutting cycle is best-effort — the batch
    # carries shutting, so recover leaves the display as-is: no reap, no drop, no
    # re-mark, since the process is going away. recover reads the flag itself, so
    # the caller cannot bypass the policy.
    recovery, provider, lifecycle, signal, attribution = _recovery()
    recovery.recover(_SHUTTING_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    assert lifecycle.calls == []
    assert provider.drops == 0
    assert provider.gets == 0
    assert signal.added == []
    assert not attribution.is_quarantined(_SCENE)  # a shutdown flush is not a crash


def test_restore_re_queues_the_exact_batch() -> None:
    recovery, _provider, _lifecycle, signal, _attribution = _recovery()
    recovery.restore(_MENU_BATCH)
    assert signal.menu_marks == 1  # restore re-queues exactly what the batch carried
    assert signal.added == [_SCENE]  # the batch's own scenes


def test_restore_re_queues_the_menu_flag_the_batch_carried() -> None:
    # restore is the generic-failure path: it does not replace the display, so it
    # re-queues exactly what the batch carried — the menu flag only when the batch
    # itself set it, unlike the heal path which always re-marks the menu.
    recovery, _provider, _lifecycle, signal, _attribution = _recovery()
    recovery.restore(_MENU_BATCH)
    assert signal.menu_marks == 1  # the batch carried a menu change

    recovery, _provider, _lifecycle, signal, _attribution = _recovery()
    recovery.restore(_BATCH)  # no menu flag on this batch
    assert signal.menu_marks == 0  # restore does not manufacture one


def test_recover_attributes_the_death_to_the_given_suspect_set() -> None:
    # The crash-quarantine wiring: recover attributes before healing, using
    # exactly the suspect set its caller determined (the whole batch, or one
    # isolation-probed scene), not the batch's own scene set unconditionally.
    other = SceneId("other")
    recovery, _provider, _lifecycle, _signal, attribution = _recovery()
    recovery.recover(_BATCH, wedged=False, suspect=frozenset({other}))
    recovery.recover(_BATCH, wedged=False, suspect=frozenset({other}))
    assert attribution.is_quarantined(other)
    assert not attribution.is_quarantined(_SCENE)


def test_a_wedged_recovery_paces_the_respawn(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("punt_lux.domain.hub.recovery.time.sleep", slept.append)
    recovery, _provider, _lifecycle, _signal, _attribution = _recovery()
    recovery.recover(_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    recovery.recover(_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    assert slept == [1.0, 2.0]  # paced, not a flat delay


def test_reset_backoff_if_stable_is_a_no_op_when_time_never_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fake clock is pinned at 0.0, so no interval ever elapses: the backoff
    # keeps climbing across respawns exactly as if reset_backoff_if_stable were
    # never called — proving it never resets early.
    slept: list[float] = []
    monkeypatch.setattr("punt_lux.domain.hub.recovery.time.sleep", slept.append)
    recovery, _provider, _lifecycle, _signal, _attribution = _recovery()
    recovery.recover(_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    recovery.reset_backoff_if_stable()
    recovery.recover(_BATCH, wedged=True, suspect=frozenset({_SCENE}))
    assert slept == [1.0, 2.0]
