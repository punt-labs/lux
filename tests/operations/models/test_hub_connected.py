"""A connected witness is immutable and must name its dial."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.operations.models.hub_connected import HubConnected


def test_named_connection() -> None:
    assert HubConnected(name="start:1").state == "connected"


@pytest.mark.parametrize(
    "payload", [{}, {"name": ""}, {"name": "x", "state": "unobserved"}]
)
def test_invalid_connection(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        HubConnected.model_validate(payload)


def test_connection_cannot_be_replaced() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        HubConnected(name="start:1").__setattr__("name", "start:2")
