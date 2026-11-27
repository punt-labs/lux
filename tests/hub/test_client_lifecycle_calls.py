"""ClientLifecycle ends a provider's pending calls in the step that ends its session.

A call pending on a session must resolve as lost in the same lifecycle step that
takes the session away: when a successor takes the listener slot, when the
connection departs, and when the lease sweep removes it (DES-107, C4). Waiting for
the socket's own teardown leaves the call pending until its deadline.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.hub.callback_ports import CallProvider
from punt_lux.hub.hub import Hub
from punt_lux.hub.hub_store_factory import HubStoreFactory
from punt_lux.hub.menu_presence import MarkMenusSink
from punt_lux.kernel.client_host import UNOBSERVED
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.model.ids import SceneId

_CONN = ConnectionId("c1")
_PAST_AN_APPLET_LEASE = 100.0


@final
class _Marker:
    def mark_dirty(self, scene_id: SceneId) -> None:
        """Ignore scene marks."""

    def mark_menus(self) -> None:
        """Ignore menu marks."""


@final
class _Clock:
    now: float
    __slots__ = ("now",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.now = 0.0
        return self

    def __call__(self) -> float:
        return self.now


@final
class _Provider:
    """A leg that serves calls and counts how often its calls were ended."""

    ended: int
    __slots__ = ("ended",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.ended = 0
        return self

    def wake(self) -> None:
        """Occupies the slot only."""

    def end_calls(self) -> None:
        self.ended += 1


def _identity() -> ClientIdentity:
    return ClientIdentity(kind="applet", name="lux · lux · #1 · term", repo="/w/lux")


def _wired() -> tuple[HubStoreFactory, _Clock]:
    clock = _Clock()
    factory = HubStoreFactory(clock, Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return factory, clock


def test_a_provider_leg_is_a_call_provider() -> None:
    assert isinstance(_Provider(), CallProvider)


def test_a_successor_taking_the_slot_ends_the_displaced_legs_calls() -> None:
    factory, _ = _wired()
    old, new = _Provider(), _Provider()
    factory.lifecycle.attach(_CONN, _identity(), old, UNOBSERVED)

    factory.lifecycle.attach(_CONN, _identity(), new, UNOBSERVED)

    assert old.ended == 1
    assert new.ended == 0


def test_attaching_the_same_leg_again_ends_nothing() -> None:
    factory, _ = _wired()
    leg = _Provider()
    factory.lifecycle.attach(_CONN, _identity(), leg, UNOBSERVED)

    factory.lifecycle.attach(_CONN, _identity(), leg, UNOBSERVED)

    assert leg.ended == 0


def test_a_departure_ends_the_legs_calls() -> None:
    factory, _ = _wired()
    leg = _Provider()
    factory.lifecycle.attach(_CONN, _identity(), leg, UNOBSERVED)

    factory.lifecycle.depart(_CONN)

    assert leg.ended == 1


def test_the_lease_sweep_ends_the_calls_of_every_lapsed_leg() -> None:
    factory, clock = _wired()
    leg = _Provider()
    factory.lifecycle.attach(_CONN, _identity(), leg, UNOBSERVED)
    clock.now = _PAST_AN_APPLET_LEASE

    left = factory.lifecycle.depart_lapsed(frozenset())

    assert left == frozenset({_CONN})
    assert leg.ended == 1


def test_a_leg_that_does_not_serve_calls_is_departed_without_error() -> None:
    class _Plain:
        def wake(self) -> None:
            """Occupies the slot only."""

    factory, _ = _wired()
    factory.lifecycle.attach(_CONN, _identity(), _Plain(), UNOBSERVED)

    factory.lifecycle.depart(_CONN)
