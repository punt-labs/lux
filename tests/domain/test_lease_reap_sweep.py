"""LeaseReapSweep sweeps lapsed leases, waits, and repeats.

The real logic is one synchronous method — ``sweep`` — driven against a real
``HubDisplay`` on a controllable clock, with no read, no other connection's
write, and no disconnect signal anywhere in the picture (TR1, the bead's own
reported scenario). One async case proves ``run`` keeps sweeping until
cancelled, mirroring ``test_expiry_sweep.py``'s pattern for the sibling
periodic task.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.lease_reap_sweep import LeaseReapSweep
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.update import AddElement

_SCENE = SceneId("sweep-scene")


@final
class _FakeClock:
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


def _cli(name: str) -> ClientIdentity:
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def test_sweep_reaps_a_lapsed_connection_with_no_other_activity() -> None:
    """TR1: kill the transport, wait, tick the reaper -- nothing else runs."""
    clock = _FakeClock()
    display = HubDisplay(clock)
    dead = ConnectionId("dead-conn")
    display.identify_client(dead, _cli("dead"))
    display.apply(
        dead,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="track"), parent_id=None),
    )
    sweep = LeaseReapSweep(display)

    clock.advance(91.0)  # past the 90s cli lease; nothing else ever touches it
    reaped = sweep.sweep()

    assert reaped == frozenset({dead})
    assert not display.is_client(dead)
    assert display.elements_owned_by(dead) == ()


def test_sweep_is_empty_when_nothing_has_lapsed() -> None:
    clock = _FakeClock()
    display = HubDisplay(clock)
    live = ConnectionId("live-conn")
    display.identify_client(live, _cli("live"))
    sweep = LeaseReapSweep(display)

    assert sweep.sweep() == frozenset()
    assert display.is_client(live)


def test_run_sweeps_until_cancelled() -> None:
    clock = _FakeClock()
    display = HubDisplay(clock)
    dead = ConnectionId("dead-conn")
    display.identify_client(dead, _cli("dead"))
    clock.advance(91.0)  # already lapsed when the loop starts
    sweep = LeaseReapSweep(display, interval_seconds=0.01)

    async def drive() -> None:
        task = asyncio.create_task(sweep.run())
        for _ in range(200):  # poll up to ~2s for the first tick to fire
            await asyncio.sleep(0.01)
            if not display.is_client(dead):
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert not display.is_client(dead)


@final
class _RaiseOnceReaper:
    """A ``LeaseReaper`` whose first sweep raises, then reaps the given connection."""

    _calls: int
    _connection_id: ConnectionId
    __slots__ = ("_calls", "_connection_id")

    def __new__(cls, connection_id: ConnectionId) -> Self:
        self = super().__new__(cls)
        self._calls = 0
        self._connection_id = connection_id
        return self

    @property
    def calls(self) -> int:
        return self._calls

    def reap_lapsed_leases(self) -> frozenset[ConnectionId]:
        self._calls += 1
        if self._calls == 1:
            msg = "reap boom"
            raise RuntimeError(msg)
        return frozenset({self._connection_id})


def test_run_survives_a_raising_sweep_cycle() -> None:
    conn = ConnectionId("conn")
    reaper = _RaiseOnceReaper(conn)
    sweep = LeaseReapSweep(reaper, interval_seconds=0.01)

    async def drive() -> None:
        task = asyncio.create_task(sweep.run())
        for _ in range(300):  # poll past the raising first cycle
            await asyncio.sleep(0.01)
            if reaper.calls >= 2:
                break
        assert not task.done()  # the raising cycle did not kill the loop
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert reaper.calls >= 2  # a later cycle ran after the raise
