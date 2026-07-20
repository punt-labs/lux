"""SendRecovery — reap/respawn vs reconnect, the consumed-clear re-mark, restore.

Unit-tests the recovery policy directly against fakes, complementing the
worker-level partitions in ``test_hub_replicator``: a wedged display is reaped
and respawned (K1/K2), a dead peer only reconnects (RC1), a consumed clear is
re-marked (RC4), a best-effort shutdown flush heals nothing (SH2), and a failed
batch is restored intact (RR1).
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
    added: list[SceneId]
    __slots__ = ("added", "cleared_marks")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.cleared_marks = 0
        self.added = []
        return self

    def mark_cleared(self) -> None:
        self.cleared_marks += 1

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
