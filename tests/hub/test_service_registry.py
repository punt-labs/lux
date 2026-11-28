"""ServiceRegistry — which connection serves which (service, host) (DES-107).

A key is held by one connection at a time. The same connection registering again
replaces its own registration; a different connection claiming a held key is
refused. A connection's registrations are withdrawn together.
"""

from __future__ import annotations

from punt_lux.hub.service_registry import ServiceKey, ServiceRegistry
from punt_lux.kernel.connection_id import ConnectionId


class _Leg:
    """A listener stand-in; what matters is which one registered."""

    def wake(self) -> None:
        """Occupy the listener slot."""


_A = ConnectionId("a")
_B = ConnectionId("b")
_TERMINAL = ServiceKey("terminal", "okinos")
_LEG_A = _Leg()
_LEG_B = _Leg()


def test_a_free_key_is_taken() -> None:
    registry = ServiceRegistry()

    assert registry.claim(_TERMINAL, _A, _LEG_A) == "registered"
    assert registry.holder(_TERMINAL) == _A


def test_the_same_connection_claiming_again_replaces_its_own_registration() -> None:
    registry = ServiceRegistry()
    registry.claim(_TERMINAL, _A, _LEG_A)

    assert registry.claim(_TERMINAL, _A, _LEG_A) == "registered"
    assert registry.holder(_TERMINAL) == _A
    assert registry.keys_of(_A) == (_TERMINAL,)


def test_a_different_connection_claiming_a_held_key_is_refused() -> None:
    registry = ServiceRegistry()
    registry.claim(_TERMINAL, _A, _LEG_A)

    assert registry.claim(_TERMINAL, _B, _LEG_B) == "held"
    assert registry.holder(_TERMINAL) == _A


def test_withdrawing_a_connection_frees_every_key_it_held() -> None:
    registry = ServiceRegistry()
    registry.claim(ServiceKey("terminal", "okinos"), _A, _LEG_A)
    registry.claim(ServiceKey("album", "okinos"), _A, _LEG_A)
    registry.claim(ServiceKey("terminal", "other"), _B, _LEG_B)

    freed = registry.withdraw(_A)

    assert set(freed) == {
        ServiceKey("terminal", "okinos"),
        ServiceKey("album", "okinos"),
    }
    assert registry.holder(_TERMINAL) is None
    assert registry.claim(_TERMINAL, _B, _LEG_B) == "registered"
    assert registry.holder(ServiceKey("terminal", "other")) == _B


def test_withdrawing_a_connection_that_holds_nothing_frees_nothing() -> None:
    assert ServiceRegistry().withdraw(_A) == ()


def test_the_listing_names_every_registration_in_a_stable_order() -> None:
    registry = ServiceRegistry()
    registry.claim(ServiceKey("terminal", "okinos"), _A, _LEG_A)
    registry.claim(ServiceKey("album", "okinos"), _B, _LEG_B)

    assert registry.listing() == (
        (ServiceKey("album", "okinos"), _B),
        (ServiceKey("terminal", "okinos"), _A),
    )


def test_hosts_serving_a_service_are_listed_for_the_unavailable_message() -> None:
    registry = ServiceRegistry()
    registry.claim(ServiceKey("terminal", "okinos"), _A, _LEG_A)
    registry.claim(ServiceKey("terminal", "pembroke"), _B, _LEG_B)
    registry.claim(ServiceKey("album", "okinos"), _B, _LEG_B)

    assert registry.hosts_serving("terminal") == ("okinos", "pembroke")
    assert registry.hosts_serving("nothing") == ()


def test_the_registered_leg_is_what_the_key_resolves_to() -> None:
    registry = ServiceRegistry()
    registry.claim(_TERMINAL, _A, _LEG_A)

    assert registry.leg_of(_TERMINAL) is _LEG_A


def test_the_same_connection_registering_again_replaces_the_leg() -> None:
    registry = ServiceRegistry()
    registry.claim(_TERMINAL, _A, _LEG_A)
    replacement = _Leg()

    registry.claim(_TERMINAL, _A, replacement)

    assert registry.leg_of(_TERMINAL) is replacement


def test_a_withdrawn_key_resolves_to_no_leg() -> None:
    registry = ServiceRegistry()
    registry.claim(_TERMINAL, _A, _LEG_A)

    registry.withdraw(_A)

    assert registry.leg_of(_TERMINAL) is None
