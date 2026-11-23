"""Probe the existing Hub route rather than accepting socket-only readiness."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from punt_lux.service._hub_display_probe import HubDisplayProbe


@pytest.mark.parametrize("reported,expected", [(502, "dial-1"), (501, None)])
def test_hub_facts_must_name_the_new_process(
    reported: int, expected: str | None
) -> None:
    payload = {
        "backend": "opengl",
        "window_width": 800,
        "window_height": 600,
        "fps": 60,
        "pid": reported,
        "uptime_seconds": 1,
        "protocol_version": "1",
        "element_kinds": 25,
        "hub_connection_id": "dial-1",
    }
    with (
        patch("punt_lux.service._readiness_http.HubPaths.read_port", return_value=8430),
        patch("punt_lux.service._readiness_http.http.client.HTTPConnection") as connect,
    ):
        response = connect.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        assert HubDisplayProbe(502, 0.25).connected() == expected
    assert connect.call_args.args == ("127.0.0.1", 8430)
    assert connect.call_args.kwargs["timeout"] == pytest.approx(0.25, abs=0.01)
    connect.return_value.request.assert_called_once_with("GET", "/display")
    connect.return_value.close.assert_called_once()


@pytest.mark.parametrize("status", [503, 504, 500])
def test_absent_display_is_pending_but_unexpected_http_error_fails(status: int) -> None:
    with (
        patch("punt_lux.service._readiness_http.HubPaths.read_port", return_value=8430),
        patch("punt_lux.service._readiness_http.http.client.HTTPConnection") as connect,
    ):
        connect.return_value.getresponse.return_value.status = status
        if status in (503, 504):
            assert not HubDisplayProbe(502, 0.25).connected()
        else:
            with pytest.raises(ConnectionError, match="HTTP 500"):
                HubDisplayProbe(502, 0.25).connected()
    connect.return_value.close.assert_called_once()


@pytest.mark.parametrize("body", [b"", b"{}", b"not json", b"x" * 65537])
def test_bad_or_oversized_facts_cannot_signal_readiness(body: bytes) -> None:
    with (
        patch("punt_lux.service._readiness_http.HubPaths.read_port", return_value=8430),
        patch("punt_lux.service._readiness_http.http.client.HTTPConnection") as connect,
    ):
        response = connect.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = body
        with pytest.raises(ConnectionError):
            HubDisplayProbe(502, 0.25).connected()
    response.read.assert_called_once_with(65536)
    connect.return_value.close.assert_called_once()


def test_no_hub_port_is_actionable() -> None:
    with (
        patch("punt_lux.service._readiness_http.HubPaths.read_port", return_value=None),
        pytest.raises(ConnectionError, match="Hub is not running"),
    ):
        HubDisplayProbe(502, 0.25).connected()


def test_unreachable_hub_is_actionable_and_closes_connection() -> None:
    with (
        patch("punt_lux.service._readiness_http.HubPaths.read_port", return_value=8430),
        patch("punt_lux.service._readiness_http.http.client.HTTPConnection") as connect,
    ):
        connect.return_value.request.side_effect = ConnectionRefusedError("unreachable")
        with pytest.raises(ConnectionError, match="unavailable"):
            HubDisplayProbe(502, 0.25).connected()
    connect.return_value.close.assert_called_once()


def test_slow_display_reply_is_pending_not_an_unreachable_hub() -> None:
    with (
        patch("punt_lux.service._readiness_http.HubPaths.read_port", return_value=8430),
        patch("punt_lux.service._readiness_http.http.client.HTTPConnection") as connect,
    ):
        connect.return_value.getresponse.side_effect = TimeoutError(
            "Display warming up"
        )
        assert not HubDisplayProbe(502, 0.25).connected()
    connect.return_value.close.assert_called_once()
