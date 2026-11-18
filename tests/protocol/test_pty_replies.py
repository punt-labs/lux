"""Reply envelopes are bounded, discriminated and reject ambiguous JSON."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.replies import FailureReply, Reply, ReplyCodec, SuccessReply


@pytest.mark.parametrize(
    "reply", [SuccessReply(1, {"channel": 2}), FailureReply(2, "not ready")]
)
def test_reply_round_trip(reply: Reply) -> None:
    assert ReplyCodec.decode(ReplyCodec.encode(reply)) == reply


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b"null",
        b"not json",
        b'{"id":1,"ok":true}',
        b'{"id":true,"ok":false,"error":"bad"}',
        b'{"id":1,"ok":false,"error":"a","error":"b"}',
        b'{"id":1,"ok":true,"result":{"n":NaN}}',
    ],
)
def test_invalid_reply(data: bytes) -> None:
    with pytest.raises(ControlError):
        ReplyCodec.decode(data)
