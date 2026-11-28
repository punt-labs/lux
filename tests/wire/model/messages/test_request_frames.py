"""The request, reply and refusal frames of the listen leg (DES-107).

The Hub sends a RequestFrame down the leg; the client answers with a ReplyFrame
or a RefusalFrame carrying the same request id. Frames are frozen, and a refusal
code outside the four known ones reads as ``fault`` rather than failing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.wire.model.messages.listen import ClientFrames, ServerFrames
from punt_lux.wire.model.messages.relay_frames import (
    RefusalFrame,
    ReplyFrame,
    RequestFrame,
)


def test_a_request_frame_parses_as_a_server_frame() -> None:
    frame = RequestFrame(
        request_id="c1a2.7",
        service="terminal",
        operation="new",
        payload={"label": "build"},
    )

    parsed = ServerFrames.validate_json(frame.model_dump_json())

    assert parsed == frame
    assert isinstance(parsed, RequestFrame)


def test_a_reply_frame_parses_as_a_client_frame() -> None:
    frame = ReplyFrame(request_id="c1a2.7", payload={"id": "t3"})

    parsed = ClientFrames.validate_json(frame.model_dump_json())

    assert parsed == frame
    assert isinstance(parsed, ReplyFrame)


def test_a_refusal_frame_parses_as_a_client_frame() -> None:
    frame = RefusalFrame(request_id="c1a2.7", code="not_found", reason="no such id")

    parsed = ClientFrames.validate_json(frame.model_dump_json())

    assert parsed == frame
    assert isinstance(parsed, RefusalFrame)


@pytest.mark.parametrize("code", ["rejected", "invalid_request", "not_found", "fault"])
def test_a_known_refusal_code_is_kept(code: str) -> None:
    assert (
        RefusalFrame.model_validate(
            {"request_id": "c1.1", "code": code, "reason": "r"}
        ).code
        == code
    )


@pytest.mark.parametrize("code", ["exploded", "", ["rejected"], 7, None])
def test_an_unknown_refusal_code_reads_as_fault(code: object) -> None:
    frame = RefusalFrame.model_validate(
        {"request_id": "c1.1", "code": code, "reason": "r"}
    )

    assert frame.code == "fault"


def test_a_frame_that_fails_validation_is_rejected_not_defaulted() -> None:
    with pytest.raises(ValidationError):
        ClientFrames.validate_python({"kind": "reply", "payload": {}})


@pytest.mark.parametrize(
    "frame",
    [
        RequestFrame(request_id="c1.1", service="s", operation="o", payload={}),
        ReplyFrame(request_id="c1.1", payload={}),
        RefusalFrame(request_id="c1.1", code="fault", reason="r"),
    ],
)
def test_the_frames_are_frozen(frame: RequestFrame | ReplyFrame | RefusalFrame) -> None:
    with pytest.raises(ValidationError):
        frame.request_id = "c1.2"
