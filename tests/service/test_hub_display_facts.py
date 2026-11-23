"""A matching Display without Hub dial metadata cannot establish stability."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from punt_lux.service._hub_display_facts import HubDisplayFacts


@pytest.mark.parametrize("identity", [None, "", "hub-dial"])
def test_a_matching_process_must_name_its_dial(identity: str | None) -> None:
    response = MagicMock(status=200)
    response.read.return_value = json.dumps(
        {
            "backend": "opengl",
            "window_width": 800,
            "window_height": 600,
            "fps": 60,
            "pid": 502,
            "uptime_seconds": 1,
            "protocol_version": "3",
            "element_kinds": 25,
            "hub_connection_id": identity,
        }
    ).encode()
    if identity:
        assert HubDisplayFacts.identity(response, 502) == identity
    else:
        with pytest.raises(ConnectionError, match="restart Hub"):
            HubDisplayFacts.identity(response, 502)
