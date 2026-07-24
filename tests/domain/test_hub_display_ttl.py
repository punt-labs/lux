"""HubDisplay arms, refreshes, and sweeps frame TTLs under the store lock.

A frame shown with a ``ttl_seconds`` is removed once its deadline passes, through
the same teardown a manual frame close uses. The clock is injected so time is a
value the test sets. These cases pin the Hub-side contract the expiry sweep and
the show path depend on: a TTL frame expires after its deadline and not before, a
frame with no TTL never expires, a re-show refreshes or clears the deadline, a
manual close disarms it, and expiry tears down every scene the frame holds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self, final

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId

_OWNER = ConnectionId("ttl-owner")
_FRAME = "ttl-frame"


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
@dataclass(frozen=True, slots=True)
class _WireLeaf:
    """Wire-shaped leaf — satisfies the Element Protocol structurally."""

    id: str
    kind: Literal["leaf"] = "leaf"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


def _show(
    display: HubDisplay,
    scene_id: SceneId,
    *,
    frame_id: str = _FRAME,
    ttl_seconds: float | None,
) -> None:
    """Install one owned root in ``scene_id`` framed by ``frame_id`` with a TTL."""
    display.show_scene(
        _OWNER,
        scene_id,
        [_WireLeaf(id=f"root-{scene_id}")],
        ScenePresentation(frame_id=frame_id),
        ttl_seconds=ttl_seconds,
    )


def test_a_ttl_frame_expires_its_scene_after_the_deadline() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _show(display, scene, ttl_seconds=5.0)
    assert display.scene_roots(scene)  # installed

    clock.advance(5.0)
    expired = display.frames.expire_due()

    assert expired == frozenset({scene})
    assert not display.scene_roots(scene)  # torn down


def test_expire_due_is_empty_before_the_deadline() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _show(display, scene, ttl_seconds=5.0)

    clock.advance(4.9)
    assert display.frames.expire_due() == frozenset()
    assert display.scene_roots(scene)  # still standing


def test_a_frame_without_ttl_never_expires() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _show(display, scene, ttl_seconds=None)

    clock.advance(10_000.0)
    assert display.frames.expire_due() == frozenset()
    assert display.scene_roots(scene)
    assert display.frames.seconds_until_next() is None


def test_a_reshow_with_a_new_ttl_refreshes_the_deadline() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _show(display, scene, ttl_seconds=5.0)

    clock.advance(4.0)
    _show(display, scene, ttl_seconds=5.0)  # re-show resets the countdown

    clock.advance(4.0)  # 8s since first show, 4s since re-show
    assert display.frames.expire_due() == frozenset()

    clock.advance(1.0)  # 5s since re-show
    assert display.frames.expire_due() == frozenset({scene})


def test_a_reshow_without_a_ttl_makes_the_frame_permanent() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _show(display, scene, ttl_seconds=5.0)

    _show(display, scene, ttl_seconds=None)  # re-show clears the deadline

    clock.advance(100.0)
    assert display.frames.expire_due() == frozenset()
    assert display.scene_roots(scene)


def test_manual_remove_frame_disarms_the_ttl() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    scene = SceneId("s")
    _show(display, scene, ttl_seconds=5.0)

    display.frames.remove_frame(_FRAME)  # user closes the frame before it expires
    assert display.frames.seconds_until_next() is None

    clock.advance(100.0)
    assert (
        display.frames.expire_due() == frozenset()
    )  # no stale sweep of a closed frame


def test_expire_due_removes_every_scene_the_frame_holds() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    first = SceneId("a")
    second = SceneId("b")
    _show(display, first, ttl_seconds=5.0)
    _show(display, second, ttl_seconds=5.0)  # same frame, re-arms the one deadline

    clock.advance(5.0)
    expired = display.frames.expire_due()

    assert expired == frozenset({first, second})
    assert not display.scene_roots(first)
    assert not display.scene_roots(second)


def test_seconds_until_next_expiry_reports_the_soonest_deadline() -> None:
    clock = FakeClock()
    display = HubDisplay(clock)
    _show(display, SceneId("a"), frame_id="fa", ttl_seconds=3.0)
    _show(display, SceneId("b"), frame_id="fb", ttl_seconds=1.0)
    assert display.frames.seconds_until_next() == 1.0
