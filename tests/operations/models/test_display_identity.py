"""Raw Display identity has no Hub dial; proxied identity can name that dial."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.operations.models.display_identity import DisplayIdentity
from punt_lux.operations.models.display_info import DisplayInfo


@pytest.mark.parametrize("dial", [None, "hub-dial"])
def test_identity_is_independent_of_process_uptime(dial: str | None) -> None:
    facts = DisplayIdentity.model_validate(
        {
            "pid": 502,
            "uptime_seconds": 5,
            "protocol_version": "3",
            "hub_connection_id": dial,
        }
    )
    assert facts.hub_connection_id.name == dial


def test_empty_identity_does_not_invent_a_process() -> None:
    with pytest.raises(ValidationError):
        DisplayIdentity.model_validate({})


@pytest.mark.parametrize("model", [DisplayIdentity, DisplayInfo])
def test_identity_is_immutable_in_both_fact_shapes(
    model: type[DisplayIdentity],
) -> None:
    facts = model.model_validate(
        {
            "pid": 502,
            "uptime_seconds": 5,
            "protocol_version": "3",
            "backend": "opengl",
            "window_width": 800,
            "window_height": 600,
            "fps": 60,
            "element_kinds": 25,
        }
    )
    with pytest.raises(ValidationError, match="frozen"):
        facts.__setattr__("pid", 503)
