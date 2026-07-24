"""FrameLifecycle expiry is tear-down-safe: a failing tear-down strands no frame.

``expire_due`` peeks the due frames, tears each down, and disarms it only after a
successful tear-down. So a tear-down that raises leaves that frame's deadline
armed to be retried on the next sweep, and frames the loop had not yet reached
keep their deadlines too — none is consumed-but-not-torn-down. These cases drive
that with a remover that raises for a chosen scene.
"""

from __future__ import annotations

from typing import Self, final

import pytest

from punt_lux.domain.hub.frame_expiry import FrameExpiry
from punt_lux.domain.hub.frame_lifecycle import FrameLifecycle
from punt_lux.domain.hub.scene_presentation import (
    ScenePresentation,
    ScenePresentationRegistry,
)
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.ids import SceneId


@final
class FakeClock:
    """A settable monotonic clock: the test moves time by ``advance``."""

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


@final
class _Remover:
    """A subtree remover that records tear-downs and can raise for one scene."""

    _fail_on: SceneId | None
    _torn: list[SceneId]
    __slots__ = ("_fail_on", "_torn")

    def __new__(cls, fail_on: SceneId | None = None) -> Self:
        self = super().__new__(cls)
        self._fail_on = fail_on
        self._torn = []
        return self

    @property
    def torn(self) -> list[SceneId]:
        return self._torn

    def stop_failing(self) -> None:
        self._fail_on = None

    def drop_scene_roots(self, scene_id: SceneId) -> None:
        if scene_id == self._fail_on:
            msg = f"tear-down boom for {scene_id}"
            raise RuntimeError(msg)
        self._torn.append(scene_id)


def _lifecycle(clock: FakeClock, remover: _Remover) -> FrameLifecycle:
    return FrameLifecycle(
        ScenePresentationRegistry(), remover, FrameExpiry(clock), StoreLock()
    )


def test_expire_due_leaves_the_frame_armed_when_its_teardown_raises() -> None:
    clock = FakeClock()
    remover = _Remover(fail_on=SceneId("s"))
    fl = _lifecycle(clock, remover)
    fl.present(SceneId("s"), ScenePresentation(frame_id="f"), 1.0)

    clock.advance(1.0)
    with pytest.raises(RuntimeError):
        fl.expire_due()

    # The raise left the deadline in place — not consumed — so the next sweep retries.
    remover.stop_failing()
    assert fl.expire_due() == frozenset({SceneId("s")})


def test_a_failed_teardown_does_not_strand_the_other_due_frames() -> None:
    clock = FakeClock()
    remover = _Remover(fail_on=SceneId("bad"))
    fl = _lifecycle(clock, remover)
    fl.present(SceneId("good"), ScenePresentation(frame_id="fg"), 1.0)
    fl.present(SceneId("bad"), ScenePresentation(frame_id="fb"), 1.0)

    clock.advance(1.0)
    with pytest.raises(RuntimeError):
        fl.expire_due()

    # Whatever the iteration order, no due frame is consumed without being torn
    # down: a second sweep (remover healed) retires everything still outstanding.
    remover.stop_failing()
    remaining = fl.expire_due()
    assert SceneId("bad") in remaining or SceneId("bad") in remover.torn
    assert SceneId("good") in remover.torn  # the good frame was torn down
