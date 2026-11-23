"""Raw facts explicitly lack a Hub connection witness."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict

import pytest
from pydantic import TypeAdapter, ValidationError

from punt_lux.wire.operations.hub_connection import HubUnobserved


def test_absence_is_explicit() -> None:
    assert asdict(HubUnobserved()) == {"state": "unobserved"}


def test_connected_state_requires_a_different_variant() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(HubUnobserved).validate_python({"state": "connected"})


def test_absence_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        HubUnobserved().__setattr__("state", "connected")
