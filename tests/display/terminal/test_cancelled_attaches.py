"""CancelledAttaches: late replies to abandoned attaches are expected, and undone."""

from __future__ import annotations

from punt_lux.display.terminal.cancelled_attaches import CancelledAttaches
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import FailureReply, SuccessReply


def _cancelled(*ids: int) -> tuple[CancelledAttaches, list[Frame]]:
    sent: list[Frame] = []
    cancelled = CancelledAttaches(sent.append, lambda _channel: None)
    cancelled.add(dict.fromkeys(ids, "n"))
    return cancelled, sent


def test_an_unknown_reply_is_not_consumed() -> None:
    cancelled, sent = _cancelled(3)
    assert not cancelled.consume(SuccessReply(4, {"channel": 9}))
    assert sent == []


def test_a_late_success_closes_the_channel_it_opened_once() -> None:
    cancelled, sent = _cancelled(3)
    assert cancelled.consume(SuccessReply(3, {"channel": 9}))
    assert sent == [Frame(9, FrameKind.CLOSE, b"")]
    assert not cancelled.consume(SuccessReply(3, {"channel": 9}))


def test_a_late_failure_is_consumed_without_a_close() -> None:
    cancelled, sent = _cancelled(3)
    assert cancelled.consume(FailureReply(3, "unknown session", False))
    assert sent == []


def test_a_success_without_a_valid_channel_sends_nothing() -> None:
    cancelled, sent = _cancelled(3, 4)
    assert cancelled.consume(SuccessReply(3, {}))
    assert cancelled.consume(SuccessReply(4, {"channel": 0}))
    assert sent == []


def test_clear_forgets_every_cancelled_request() -> None:
    cancelled, _ = _cancelled(3)
    cancelled.clear()
    assert not cancelled.consume(SuccessReply(3, {"channel": 9}))


def test_a_late_success_reports_its_channel_released() -> None:
    released: list[int] = []
    cancelled = CancelledAttaches(lambda _frame: None, released.append)
    cancelled.add({3: "n"})
    cancelled.consume(SuccessReply(3, {"channel": 9}))
    assert released == [9]


def test_a_name_is_outstanding_until_its_cancelled_reply_is_read() -> None:
    cancelled, _ = _cancelled(3)
    assert cancelled.outstanding("n")
    assert not cancelled.outstanding("other")
    cancelled.consume(FailureReply(3, "gone", False))
    assert not cancelled.outstanding("n")
