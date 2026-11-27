"""ClientLifecycle registers the services a client serves (DES-107).

A client registers a service by name; the key is ``(service, host)`` with the host
its identity declared. Registration needs a live listen leg and an identity, as a
menu callback does, and is withdrawn in the same lifecycle step that takes the leg
away: a successor taking the slot, a detach, a departure, the lease sweep.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.hub.hub import Hub
from punt_lux.hub.hub_store_factory import HubStoreFactory
from punt_lux.hub.menu_presence import MarkMenusSink
from punt_lux.hub.service_registry import ServiceKey
from punt_lux.kernel.client_host import UNOBSERVED
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.model.ids import SceneId

_A = ConnectionId("a")
_B = ConnectionId("b")
_KEY = ServiceKey("terminal", "okinos")
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
class _Leg:
    def wake(self) -> None:
        """Occupies the slot only."""


def _identity(host: str = "okinos") -> ClientIdentity:
    return ClientIdentity(
        kind="applet", name="lux · lux · #1 · term", repo="/w/lux", host=host
    )


def _wired() -> tuple[HubStoreFactory, _Clock]:
    clock = _Clock()
    factory = HubStoreFactory(clock, Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return factory, clock


def _served(connection: ConnectionId = _A) -> tuple[HubStoreFactory, _Clock]:
    factory, clock = _wired()
    factory.lifecycle.attach(connection, _identity(), _Leg(), UNOBSERVED)
    return factory, clock


def test_a_connection_with_a_leg_and_identity_registers_a_service() -> None:
    factory, _ = _served()

    outcome = factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    assert outcome == "registered"
    assert factory.lifecycle.service_holder(_KEY) == _A


def test_the_key_host_is_the_identitys_declared_host() -> None:
    factory, _ = _wired()
    factory.lifecycle.attach(_A, _identity("pembroke"), _Leg(), UNOBSERVED)

    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    assert factory.lifecycle.service_holder(ServiceKey("terminal", "pembroke")) == _A
    assert factory.lifecycle.service_holder(_KEY) is None


def test_a_connection_with_no_leg_is_superseded() -> None:
    factory, _ = _wired()

    assert factory.lifecycle.register_service(_A, "terminal", UNOBSERVED) == (
        "superseded"
    )


def test_an_anonymous_connection_holds_no_leg_so_it_is_superseded() -> None:
    factory, _ = _wired()
    factory.lifecycle.arrive(_A, UNOBSERVED)

    assert factory.lifecycle.register_service(_A, "terminal", UNOBSERVED) == (
        "superseded"
    )


def test_registering_is_a_contact_that_revives_a_lapsed_lease() -> None:
    factory, clock = _served()
    clock.now = _PAST_AN_APPLET_LEASE

    assert factory.lifecycle.register_service(_A, "terminal", UNOBSERVED) == (
        "registered"
    )
    assert factory.lifecycle.service_holder(_KEY) == _A


def test_a_different_connection_claiming_a_held_key_is_held() -> None:
    factory, _ = _served(_A)
    factory.lifecycle.attach(_B, _identity(), _Leg(), UNOBSERVED)
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    assert factory.lifecycle.register_service(_B, "terminal", UNOBSERVED) == "held"
    assert factory.lifecycle.service_holder(_KEY) == _A


def test_registering_again_from_the_same_connection_replaces_its_own() -> None:
    factory, _ = _served()
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    assert factory.lifecycle.register_service(_A, "terminal", UNOBSERVED) == (
        "registered"
    )


def test_a_successor_taking_the_slot_withdraws_the_displaced_legs_services() -> None:
    factory, _ = _served()
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    factory.lifecycle.attach(_A, _identity(), _Leg(), UNOBSERVED)

    assert factory.lifecycle.service_holder(_KEY) is None


def test_a_detach_withdraws_the_connections_services() -> None:
    factory, _ = _wired()
    leg = _Leg()
    factory.lifecycle.attach(_A, _identity(), leg, UNOBSERVED)
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    factory.lifecycle.detach(_A, leg)

    assert factory.lifecycle.service_holder(_KEY) is None


def test_a_departure_withdraws_the_connections_services() -> None:
    factory, _ = _served()
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    factory.lifecycle.depart(_A)

    assert factory.lifecycle.service_holder(_KEY) is None


def test_the_lease_sweep_withdraws_the_services_of_every_lapsed_connection() -> None:
    factory, clock = _served()
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)
    clock.now = _PAST_AN_APPLET_LEASE

    factory.lifecycle.depart_lapsed(frozenset())

    assert factory.lifecycle.service_holder(_KEY) is None


def test_the_hosts_serving_a_service_and_the_listing_read_the_registry() -> None:
    factory, _ = _served()
    factory.lifecycle.register_service(_A, "terminal", UNOBSERVED)

    assert factory.lifecycle.hosts_serving("terminal") == ("okinos",)
    assert factory.lifecycle.services() == ((_KEY, _A),)
