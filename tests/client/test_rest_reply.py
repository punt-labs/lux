"""RestReply — one HTTP response read into a typed result or a mapped OpError.

The client's error-mapping tests exercise RestReply through the whole client;
these pin its three branches directly: a 2xx that parses, a 2xx that does not,
and a mapped error status.
"""

from __future__ import annotations

import pytest

from punt_lux.client.rest_reply import RestReply
from punt_lux.client.rest_transport import HttpResponse
from punt_lux.wire.operations import OpError, SceneShown


def test_a_2xx_parses_into_the_expected_model() -> None:
    reply = RestReply(HttpResponse(status=200, body=b'{"kind":"ok","scene_id":"s1"}'))
    assert reply.read(SceneShown) == SceneShown(scene_id="s1")


def test_a_2xx_of_the_wrong_shape_is_a_fault_with_a_snippet() -> None:
    reply = RestReply(HttpResponse(status=200, body=b'{"wrong":"shape"}'))
    result = reply.read(SceneShown)
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert '{"wrong":"shape"}' in result.reason


@pytest.mark.parametrize(
    ("status", "code"),
    [
        # 401 must read back as identification_required, matching HttpErrorMap —
        # a challenge the client can recognize, not a downgraded "fault".
        (401, "identification_required"),
        (422, "invalid_request"),
        (404, "not_found"),
        (409, "rejected"),
        (502, "fault"),
        (503, "display_unavailable"),
        (504, "timeout"),
    ],
)
def test_an_error_status_maps_to_its_op_error_code(status: int, code: str) -> None:
    reply = RestReply(HttpResponse(status=status, body=b'{"detail":"nope"}'))
    assert reply.read(SceneShown) == OpError(code=code, reason="nope")  # type: ignore[arg-type]  # code is a parametrized OpErrorCode literal


def test_an_unmapped_status_is_a_fault() -> None:
    reply = RestReply(HttpResponse(status=500, body=b"boom"))
    result = reply.read(SceneShown)
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert result.reason == "boom"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (503, "provider_unavailable"),
        (502, "provider_lost"),
        (502, "fault"),
        (503, "display_unavailable"),
        (504, "timeout"),
    ],
)
def test_the_code_in_the_body_wins_over_the_status(status: int, code: str) -> None:
    body = f'{{"detail":"nope","code":"{code}"}}'.encode()

    result = RestReply(HttpResponse(status=status, body=body)).read(SceneShown)

    assert result == OpError(code=code, reason="nope")  # type: ignore[arg-type]  # a parametrized OpErrorCode literal


def test_an_unknown_code_in_the_body_falls_back_to_the_status() -> None:
    body = b'{"detail":"nope","code":"from_a_newer_hub"}'

    result = RestReply(HttpResponse(status=409, body=body)).read(SceneShown)

    assert result == OpError(code="rejected", reason="nope")


def test_a_body_without_a_code_keeps_reading_by_status() -> None:
    result = RestReply(HttpResponse(status=404, body=b'{"detail":"gone"}')).read(
        SceneShown
    )

    assert result == OpError(code="not_found", reason="gone")
