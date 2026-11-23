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
from punt_lux.wire.model import QueryResponse

if TYPE_CHECKING:
    from punt_lux.hub.display_requests import DisplayRequests


@pytest.mark.parametrize("method", ["get_display_info", "get_theme"])
def test_identity_belongs_to_the_pinned_dial_not_the_display(method: str) -> None:
    port = MagicMock()
    port.query.return_value = QueryResponse(
        method=method, result={"hub_connection_id": "spoofed"}
    )
    port.dial.__str__.return_value = "hub-dial"
    reply = DisplayQuery.run(cast("DisplayRequests", port), method, {})
    assert isinstance(reply, DisplayReplied)
    expected = "hub-dial" if method == "get_display_info" else "spoofed"
    assert reply.payload["hub_connection_id"] == expected
    port.query.assert_called_once_with(method, {})


def test_no_reply_is_a_timeout() -> None:
    port = MagicMock()
    port.query.return_value = None
    assert DisplayQuery.run(port, "get_display_info", {}) == DisplayFault(
        code="timeout"
    )


def test_display_error_is_not_replaced_with_identity_metadata() -> None:
    port = MagicMock()
    port.query.return_value = QueryResponse(
        method="get_display_info", error="unavailable"
    )
    assert DisplayQuery.run(port, "get_display_info", {}) == DisplayErrored(
        message="unavailable"
    )
