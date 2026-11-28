"""RegisterServiceRequest.parse -- a bad service name is an OpError, not a raise."""

from __future__ import annotations

from punt_lux.wire.operations import OpError
from punt_lux.wire.operations.service_requests import RegisterServiceRequest


def test_parse_of_a_valid_name_is_the_request() -> None:
    assert RegisterServiceRequest.parse("terminal") == RegisterServiceRequest(
        service="terminal"
    )


def test_parse_of_a_malformed_name_is_an_invalid_request_error() -> None:
    result = RegisterServiceRequest.parse("Not A Name")

    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "service" in result.reason
