"""Discriminated Hub state is immutable and has a scalar wire codec."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.wire.operations.hub_connection import (
    HubConnected,
    HubConnection,
    HubUnobserved,
)


@pytest.mark.parametrize("wire", [None, "", "hub-start:1"])
def test_wire_state_roundtrip(wire: str | None) -> None:
    connection = HubConnection.model_validate(wire)
    assert connection.model_dump() == (wire or None)
    if wire:
        assert isinstance(connection.root, HubConnected)
        assert connection.name == wire
    else:
        assert isinstance(connection.root, HubUnobserved)
        assert connection.name is None


def test_default_state_is_unobserved_and_frozen() -> None:
    connection = HubConnection()
    assert isinstance(connection.root, HubUnobserved)
    with pytest.raises(ValidationError, match="frozen"):
        connection.__setattr__("root", HubConnected(name="other"))


def test_observed_connection_selects_the_connected_variant() -> None:
    connection = HubConnection.observed("hub-start:2")
    assert isinstance(connection.root, HubConnected)
    assert connection.model_dump() == "hub-start:2"


def test_observed_connection_requires_a_nonempty_name() -> None:
    with pytest.raises(ValidationError):
        HubConnection.observed("")


@pytest.mark.parametrize("bad", [12, {}, {"state": "other"}])
def test_invalid_wire_state_is_rejected(bad: object) -> None:
    with pytest.raises(ValidationError):
        HubConnection.model_validate(bad)
