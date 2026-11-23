"""Transient attach errors back off; permanent errors survive reconnect."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.display.terminal.attachment_requests import AttachmentRequests
from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.terminal.snapshot import encode_binary, snapshot_version, tracked_terminal
from punt_lux.wire.stream.frames import Frame
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply


def test_transient_failure_retries_with_capped_backoff_and_then_attaches() -> None:
    sent: list[Frame] = []
    requests = AttachmentRequests(sent.append, lambda _channel: None)
    session = RemoteSession("shell", "", sent.append)
    try:
        requests.hello(1)
        requests.receive(ReplyCodec.encode(SuccessReply(1, {})))
        assert requests.ready
        now = 100.0
        for request_id, delay in enumerate([0.25, 0.5, 1, 2, 4, 4], start=2):
            requests.attach(request_id, session)
            with patch(
                "punt_lux.display.terminal.attachment_requests.time.monotonic",
                return_value=now,
            ):
                assert (
                    requests.receive(
                        ReplyCodec.encode(FailureReply(request_id, "busy", True))
                    )
                    is None
                )
                assert session.phase is RemotePhase.DISCONNECTED
                assert requests.due() == ()
            with patch(
                "punt_lux.display.terminal.attachment_requests.time.monotonic",
                return_value=now + delay - 0.001,
            ):
                assert requests.due() == ()
            now += delay
            with patch(
                "punt_lux.display.terminal.attachment_requests.time.monotonic",
                return_value=now,
            ):
                assert requests.due() == (session,)
                assert requests.due() == ()
        requests.attach(20, session)
        term = tracked_terminal(20, 4)
        data = encode_binary(term)
        assert (
            requests.receive(
                ReplyCodec.encode(
                    SuccessReply(
                        20,
                        {
                            "session": "shell",
                            "position": 0,
                            "cols": 20,
                            "rows": 4,
                            "snapshot_version": snapshot_version(),
                            "format": "binary",
                            "size": len(data),
                            "channel": 1,
                            "ended": False,
                            "exit_code": None,
                        },
                    )
                )
            )
            is session
        )
        assert session.phase is RemotePhase.SNAPSHOT
        term.close()
    finally:
        session.close()


def test_invalid_request_remains_failed_across_reconnection() -> None:
    sent: list[Frame] = []
    requests = AttachmentRequests(sent.append, lambda _channel: None)
    session = RemoteSession("shell", "", sent.append)
    try:
        requests.attach(1, session)
        requests.receive(ReplyCodec.encode(FailureReply(1, "conflicting command")))
        assert session.phase is RemotePhase.FAILED
        assert requests.due() == ()
        requests.disconnect((session,), "connection lost")
        requests.attach(2, session)
        assert session.phase is RemotePhase.FAILED
        assert len(sent) == 1
    finally:
        session.close()


def test_empty_queue_and_uncorrelated_reply() -> None:
    requests = AttachmentRequests(lambda _frame: None, lambda _channel: None)
    assert requests.due() == ()
    with pytest.raises(ValueError, match="unexpected"):
        requests.receive(ReplyCodec.encode(FailureReply(99, "unexpected")))
