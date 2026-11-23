"""Raw Display identity has no Hub dial; proxied identity can name that dial."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.operations.models.display_identity import DisplayIdentity


@pytest.mark.parametrize("dial", [None, "hub-dial"])
def test_identity_is_independent_of_process_uptime(dial: str | None) -> None:
    facts = DisplayIdentity(
        pid=502, uptime_seconds=5, protocol_version="3", hub_connection_id=dial
    )
    assert facts.hub_connection_id == dial


def test_empty_identity_does_not_invent_a_process() -> None:
    with pytest.raises(ValidationError):
        DisplayIdentity.model_validate({})
