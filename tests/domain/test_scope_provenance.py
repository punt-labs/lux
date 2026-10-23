"""Scope -- where a caller came from decides its host and whether it is a contact."""

from __future__ import annotations

from typing import get_args

import pytest

from punt_lux.client_host import UNOBSERVED, ClientHost
from punt_lux.domain.ids import ConnectionId
from punt_lux.domain.scope import Provenance, Scope

_CONN = ConnectionId("c1")
_PEER = ClientHost("10.0.0.5")


def test_an_observed_scope_carries_the_host_its_transport_reported() -> None:
    scope = Scope.observed(_CONN, _PEER)

    assert (scope.client_host, scope.is_contact) == (_PEER, True)


def test_an_observed_scope_with_no_peer_is_an_in_process_scope() -> None:
    scope = Scope.observed(_CONN, UNOBSERVED)

    assert scope.provenance == "in_process"


def test_an_in_process_scope_is_a_contact_with_no_host() -> None:
    scope = Scope.in_process(_CONN)

    assert (scope.client_host, scope.is_contact) == (UNOBSERVED, True)


def test_an_act_on_behalf_of_an_owner_is_not_a_contact() -> None:
    scope = Scope.on_behalf_of(_CONN)

    assert (scope.client_host, scope.is_contact) == (UNOBSERVED, False)


def test_a_client_side_scope_is_not_a_hub_contact() -> None:
    scope = Scope.client_side(_CONN)

    assert (scope.client_host, scope.is_contact) == (UNOBSERVED, False)


def test_a_scope_cannot_be_built_without_saying_where_it_came_from() -> None:
    with pytest.raises(TypeError):
        Scope(_CONN)  # type: ignore[call-arg]


def test_provenance_and_host_are_not_part_of_a_scopes_identity() -> None:
    assert Scope.observed(_CONN, _PEER) == Scope.on_behalf_of(_CONN)


@pytest.mark.parametrize("provenance", ["in_process", "on_behalf_of", "client_side"])
def test_a_scope_that_is_not_observed_refuses_a_host(provenance: Provenance) -> None:
    with pytest.raises(ValueError, match="only an observed scope"):
        Scope(_CONN, _PEER, provenance)


def test_an_observed_scope_refuses_no_host() -> None:
    with pytest.raises(ValueError, match="only an observed scope"):
        Scope(_CONN, UNOBSERVED, "observed")


def test_a_scope_refuses_a_provenance_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="unknown scope provenance"):
        Scope(_CONN, UNOBSERVED, "bogus")  # type: ignore[arg-type]


@pytest.mark.parametrize("provenance", get_args(Provenance))
def test_every_provenance_says_whether_it_is_a_contact(provenance: Provenance) -> None:
    host = _PEER if provenance == "observed" else UNOBSERVED

    scope = Scope(_CONN, host, provenance)

    assert scope.is_contact == (provenance in ("observed", "in_process"))
