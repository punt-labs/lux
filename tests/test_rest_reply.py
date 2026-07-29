"""RestReply — one HTTP response read into a typed result or a mapped OpError.

The client's error-mapping tests exercise RestReply through the whole client;
these pin its three branches directly: a 2xx that parses, a 2xx that does not,
and a mapped error status.
"""

from __future__ import annotations

import pytest

from punt_lux.operations import OpError, SceneShown
from punt_lux.rest_reply import RestReply
from punt_lux.rest_transport import HttpResponse


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
