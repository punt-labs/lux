"""Only successful Display facts carry the pinned Hub dial's identity."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from punt_lux.operations.display_query import DisplayQuery
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)
from punt_lux.operations.models.hub_connection import HubConnection
from punt_lux.service._display_stability import DisplayStability
from punt_lux.wire.model import QueryResponse

if TYPE_CHECKING:
    from punt_lux.hub.display_requests import DisplayRequests


@pytest.mark.parametrize("method", ["get_display_info", "get_theme"])
def test_identity_belongs_to_the_pinned_dial_not_the_display(method: str) -> None:
    port = MagicMock()
    port.query.return_value = QueryResponse(
        method=method, result={"hub_connection_id": "spoofed"}
    )
    port.connection_id = "hub-dial"
    reply = DisplayQuery.run(cast("DisplayRequests", port), method, {})
    assert isinstance(reply, DisplayReplied)
    assert reply.payload["hub_connection_id"] == "spoofed"
    assert isinstance(reply.connection, HubConnection)
    assert reply.connection.name == "hub-dial"
    port.query.assert_called_once_with(method, {})


def test_no_reply_is_a_timeout() -> None:
    port = MagicMock()
    port.query.return_value = None
    assert DisplayQuery.run(port, "get_display_info", {}) == DisplayFault.TIMEOUT


def test_display_error_is_not_replaced_with_identity_metadata() -> None:
    port = MagicMock()
    port.query.return_value = QueryResponse(
        method="get_display_info", error="unavailable"
    )
    assert DisplayQuery.run(port, "get_display_info", {}) == DisplayErrored(
        message="unavailable"
    )


def test_real_dial_names_survive_query_resolution_and_reset_stability() -> None:
    port = MagicMock()
    port.query.return_value = QueryResponse(method="get_display_info", result={})
    first = "hub-start:1"
    second = "hub-start:2"
    window = DisplayStability(3)
    for dial, now, expected in [
        (first, 0, False),
        (second, 3, False),
        (second, 6, True),
    ]:
        port.connection_id = dial
        reply = DisplayQuery.run(port, "get_display_info", {})
        assert isinstance(reply, DisplayReplied)
        assert isinstance(reply.connection, HubConnection)
        identity = reply.connection.name
        assert identity == dial
        assert window.observe(identity, (now, now)) is expected
