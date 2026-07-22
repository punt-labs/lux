"""SendRecovery — reap/respawn vs reconnect, the consumed-clear re-mark, restore.

Unit-tests the recovery policy directly against fakes, complementing the
worker-level partitions in ``test_hub_replicator``: a wedged display is reaped
and respawned (K1/K2), a dead peer only reconnects (RC1), a consumed clear is
re-marked (RC4), a best-effort shutdown flush heals nothing (SH2), a failed batch
is restored intact (RR1), and the menu is re-marked unconditionally on the heal
path — the agent bar's analog of the always-re-mark of live scenes — so a display
that came back blank gets the bar re-pushed even when the failed batch carried no
menu change, while ``restore`` re-marks the menu only when the batch itself did.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.hub.dirty_signal import DrainedBatch
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.domain.hub.dirty_signal import DirtySignal
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle
    from punt_lux.domain.hub.scene_snapshot import SceneReader


class _FakeProvider:
    """Counts drops."""

    drops: int
    __slots__ = ("drops",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.drops = 0
        return self

    def get(self) -> object:
        return self

    def drop(self) -> None:
        self.drops += 1


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

    cleared_marks: int
    menu_marks: int
    added: list[SceneId]
    __slots__ = ("added", "cleared_marks", "menu_marks")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.cleared_marks = 0
        self.menu_marks = 0
        self.added = []
        return self

    def mark_cleared(self) -> None:
        self.cleared_marks += 1

    def mark_menus(self) -> None:
        self.menu_marks += 1

    def add_all(self, scenes: Iterable[SceneId]) -> None:
        self.added.extend(scenes)


class _FakeReader:
    """Returns a fixed live-scene set."""

    _live: tuple[SceneId, ...]
    __slots__ = ("_live",)

    def __new__(cls, live: tuple[SceneId, ...]) -> Self:
        self = super().__new__(cls)
        self._live = live
        return self

    def live_scene_ids(self) -> tuple[SceneId, ...]:
        return self._live


def _recovery(
    live: tuple[SceneId, ...],
) -> tuple[SendRecovery, _FakeProvider, _FakeLifecycle, _FakeSignal]:
    provider = _FakeProvider()
    lifecycle = _FakeLifecycle()
    signal = _FakeSignal()
    reader = _FakeReader(live)
    recovery = SendRecovery(
        cast("ClientProvider", provider),
        cast("DisplayLifecycle", lifecycle),
        cast("DirtySignal", signal),
        cast("SceneReader", reader),
    )
    return recovery, provider, lifecycle, signal


_SCENE = SceneId("s1")
_BATCH = DrainedBatch(frozenset({_SCENE}), cleared=False, shutting=False)
_CLEARED_BATCH = DrainedBatch(frozenset({_SCENE}), cleared=True, shutting=False)
_SHUTTING_BATCH = DrainedBatch(frozenset({_SCENE}), cleared=False, shutting=True)
_MENU_BATCH = DrainedBatch(
    frozenset({_SCENE}), cleared=False, shutting=False, menus_dirty=True
)


def test_a_wedged_display_is_reaped_then_respawned_then_remarked() -> None:
    recovery, provider, lifecycle, signal = _recovery((_SCENE,))
    recovery.recover(_BATCH, wedged=True)
    assert lifecycle.calls == ["reap", "ensure"]  # kill before respawn
    assert provider.drops == 1
    assert signal.added == [_SCENE]  # every live scene re-marked


def test_a_dead_peer_reconnects_without_reaping() -> None:
    recovery, provider, lifecycle, signal = _recovery((_SCENE,))
    recovery.recover(_BATCH, wedged=False)
    assert lifecycle.calls == []  # nothing killed
    assert provider.drops == 1
    assert signal.added == [_SCENE]


def test_recovery_of_a_cleared_batch_re_marks_the_clear() -> None:
    recovery, _provider, _lifecycle, signal = _recovery((_SCENE,))
    recovery.recover(_CLEARED_BATCH, wedged=False)
    assert signal.cleared_marks == 1  # the consumed clear is re-marked
    assert signal.added == [_SCENE]


def test_recovery_re_marks_the_menu_even_for_a_scene_only_batch() -> None:
    # The headline fix at the recovery unit: a scene-only failure (the batch carried
    # no menu change) still re-marks the menu, so a display that came back blank gets
    # the agent bar re-pushed. This mirrors the always-re-mark of live scenes; the
    # worker's fresh registry read at send time supplies the current bar (or a
    # harmless blank if none is set).
    recovery, _provider, _lifecycle, signal = _recovery((_SCENE,))
    recovery.recover(_BATCH, wedged=True)  # batch has no menu flag set
    assert signal.menu_marks == 1  # the menu is re-marked anyway
    assert signal.added == [_SCENE]


def test_a_shutdown_flush_heals_nothing() -> None:
    # SH2: a send that fails during the shutting cycle is best-effort — the batch
    # carries shutting, so recover leaves the display as-is: no reap, no drop, no
    # re-mark, since the process is going away. recover reads the flag itself, so
    # the caller cannot bypass the policy.
    recovery, provider, lifecycle, signal = _recovery((_SCENE,))
    recovery.recover(_SHUTTING_BATCH, wedged=True)
    assert lifecycle.calls == []
    assert provider.drops == 0
    assert signal.added == []


def test_restore_re_queues_the_exact_batch() -> None:
    recovery, _provider, _lifecycle, signal = _recovery(())
    recovery.restore(_CLEARED_BATCH)
    assert signal.cleared_marks == 1
    assert signal.added == [_SCENE]  # the batch's own scenes, not live_scene_ids


def test_restore_re_queues_the_menu_flag_the_batch_carried() -> None:
    # restore is the generic-failure path: it does not replace the display, so it
    # re-queues exactly what the batch carried — the menu flag only when the batch
    # itself set it, unlike the heal path which always re-marks the menu.
    recovery, _provider, _lifecycle, signal = _recovery(())
    recovery.restore(_MENU_BATCH)
    assert signal.menu_marks == 1  # the batch carried a menu change

    recovery, _provider, _lifecycle, signal = _recovery(())
    recovery.restore(_BATCH)  # no menu flag on this batch
    assert signal.menu_marks == 0  # restore does not manufacture one
