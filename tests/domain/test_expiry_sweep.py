"""ExpirySweep waits to the next deadline, sweeps due frames, and marks them dirty.

The sweep's real logic is two synchronous methods — ``next_wait`` (how long to
sleep) and ``sweep`` (retire due frames, mark their scenes) — driven against a
real ``FrameLifecycle`` on a controllable clock, plus a stub frame source for the
wait-selection edges. One async case proves ``run`` keeps sweeping until cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self, final

import pytest

from punt_lux.domain.hub.expiry_sweep import ExpirySweep
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId

_OWNER = ConnectionId("sweep-owner")


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
class SpyMarker:
    """Records the scenes marked dirty; a stand-in for the replicator."""

    _marked: list[SceneId]
    __slots__ = ("_marked",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._marked = []
        return self

    @property
    def marked(self) -> list[SceneId]:
        return self._marked

    def mark_dirty(self, scene_id: SceneId) -> None:
        self._marked.append(scene_id)

    def mark_cleared(self) -> None:  # pragma: no cover - unused by the sweep
        raise AssertionError("sweep never clears the whole display")

    def mark_menus(self) -> None:  # pragma: no cover - unused by the sweep
        raise AssertionError("sweep never touches menus")


@final
@dataclass(frozen=True, slots=True)
class _WireLeaf:
    id: str
    kind: Literal["leaf"] = "leaf"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


@final
class _StubFrames:
    """A scripted ``ExpiryFrames``: a fixed wait and a queue of due-scene sets."""

    _wait: float | None
    _due: list[frozenset[SceneId]]
    __slots__ = ("_due", "_wait")

    def __new__(cls, wait: float | None, due: list[frozenset[SceneId]]) -> Self:
        self = super().__new__(cls)
        self._wait = wait
        self._due = list(due)
        return self

    def seconds_until_next(self) -> float | None:
        return self._wait

    def expire_due(self) -> frozenset[SceneId]:
        return self._due.pop(0) if self._due else frozenset()


def _seed(display: HubDisplay, scene: SceneId, *, ttl_seconds: float) -> None:
    display.show_scene(
        _OWNER,
        scene,
        [_WireLeaf(id=f"root-{scene}")],
        ScenePresentation(frame_id=str(scene)),
        ttl_seconds=ttl_seconds,
    )


def test_sweep_marks_and_tears_down_a_due_frame() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _seed(display, scene, ttl_seconds=5.0)
    marker = SpyMarker()
    sweep = ExpirySweep(display.frames, marker)

    clock.advance(5.0)
    sweep.sweep()

    assert marker.marked == [scene]
    assert not display.scene_roots(scene)


def test_sweep_marks_nothing_before_the_deadline() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    _seed(display, SceneId("s"), ttl_seconds=5.0)
    marker = SpyMarker()
    sweep = ExpirySweep(display.frames, marker)

    clock.advance(4.0)
    sweep.sweep()

    assert marker.marked == []


def test_next_wait_is_the_soonest_deadline_when_within_the_cap() -> None:
    sweep = ExpirySweep(_StubFrames(wait=0.5, due=[]), SpyMarker())
    assert sweep.next_wait() == 0.5


def test_next_wait_idles_when_nothing_is_armed() -> None:
    sweep = ExpirySweep(_StubFrames(wait=None, due=[]), SpyMarker())
    assert sweep.next_wait() == 1.0


def test_next_wait_clamps_a_passed_deadline_to_zero() -> None:
    sweep = ExpirySweep(_StubFrames(wait=-3.0, due=[]), SpyMarker())
    assert sweep.next_wait() == 0.0


def test_next_wait_caps_a_far_deadline_at_the_idle_poll() -> None:
    # A distant deadline must not make the loop sleep past a nearer one armed while
    # it waits: the wait is capped so the loop re-checks within the idle poll.
    sweep = ExpirySweep(_StubFrames(wait=3600.0, due=[]), SpyMarker())
    assert sweep.next_wait() == 1.0


def test_run_sweeps_until_cancelled() -> None:
    scene = SceneId("x")
    frames = _StubFrames(wait=0.0, due=[frozenset({scene})])
    marker = SpyMarker()
    sweep = ExpirySweep(frames, marker)

    async def drive() -> None:
        task = asyncio.create_task(sweep.run())
        await asyncio.sleep(0.02)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert scene in marker.marked


@final
class _RaiseOnceFrames:
    """An ``ExpiryFrames`` whose first ``expire_due`` raises, then yields a scene."""

    _raised: bool
    _scene: SceneId
    __slots__ = ("_raised", "_scene")

    def __new__(cls, scene: SceneId) -> Self:
        self = super().__new__(cls)
        self._raised = False
        self._scene = scene
        return self

    def seconds_until_next(self) -> float | None:
        return 0.0

    def expire_due(self) -> frozenset[SceneId]:
        if not self._raised:
            self._raised = True
            msg = "sweep boom"
            raise RuntimeError(msg)
        return frozenset({self._scene})


def test_run_survives_a_raising_sweep_cycle() -> None:
    scene = SceneId("x")
    marker = SpyMarker()
    sweep = ExpirySweep(_RaiseOnceFrames(scene), marker)

    async def drive() -> None:
        task = asyncio.create_task(sweep.run())
        for _ in range(200):
            await asyncio.sleep(0.001)
            if marker.marked:
                break
        assert not task.done()  # the raising cycle did not kill the loop
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert scene in marker.marked  # a later cycle swept after the raise


@pytest.mark.integration
def test_run_expires_a_real_frame_end_to_end() -> None:
    """A real ``FrameLifecycle`` on the monotonic clock, swept by a real loop.

    Not a latency bound: a short real TTL is armed and the sweep is polled until it
    fires (up to a generous window), proving the loop actually retires an armed
    frame through the real expiry path — not a stubbed one.
    """
    display = HubDisplay()  # real monotonic clock
    scene = SceneId("real")
    display.show_scene(
        _OWNER,
        scene,
        [_WireLeaf(id="r")],
        ScenePresentation(frame_id="real"),
        ttl_seconds=0.05,
    )
    marker = SpyMarker()
    sweep = ExpirySweep(display.frames, marker)

    async def drive() -> None:
        task = asyncio.create_task(sweep.run())
        for _ in range(200):  # poll up to ~2s for the 0.05s TTL to fire
            await asyncio.sleep(0.01)
            if marker.marked:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert marker.marked == [scene]
    assert not display.scene_roots(scene)


@pytest.mark.integration
def test_run_sweeps_a_short_deadline_armed_after_a_far_one() -> None:
    """A near deadline armed while the loop waits on a far one still fires promptly.

    The regression guard for the wait cap: a frame is armed an hour out, the sweep
    starts (its first wait is capped, not an hour), then a second frame is armed a
    blink out. Without the cap the loop would sleep ~an hour and the short frame
    would linger; with it, the short frame retires within about the idle poll.
    """
    display = HubDisplay()  # real monotonic clock
    far = SceneId("far")
    near = SceneId("near")
    display.show_scene(
        _OWNER,
        far,
        [_WireLeaf(id="f")],
        ScenePresentation(frame_id="far"),
        ttl_seconds=3600.0,
    )
    marker = SpyMarker()
    sweep = ExpirySweep(display.frames, marker)

    async def drive() -> None:
        task = asyncio.create_task(sweep.run())
        await asyncio.sleep(0.02)  # let the loop enter its (capped) first wait
        display.show_scene(
            _OWNER,
            near,
            [_WireLeaf(id="n")],
            ScenePresentation(frame_id="near"),
            ttl_seconds=0.02,
        )
        for _ in range(200):  # poll up to ~2s — well under the 1s cap + margin
            await asyncio.sleep(0.01)
            if near in marker.marked:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert near in marker.marked  # the near frame fired
    assert far not in marker.marked  # the far one is still an hour out
    assert not display.scene_roots(near)
    assert display.scene_roots(far)
