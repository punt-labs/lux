"""Raw facts explicitly lack a Hub connection witness."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.operations.models.hub_unobserved import HubUnobserved


def test_absence_is_explicit() -> None:
    assert HubUnobserved().model_dump() == {"state": "unobserved"}


def test_connected_state_requires_a_different_variant() -> None:
    with pytest.raises(ValidationError):
        HubUnobserved.model_validate({"state": "connected"})


def test_absence_is_immutable() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        HubUnobserved().__setattr__("state", "connected")
