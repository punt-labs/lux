"""A viewer's queued bytes leave in order: snapshot, live output, then CLOSE."""

from __future__ import annotations

from punt_lux.pty.close_notice import CloseNotice
from punt_lux.pty.credit import CreditWindow
from punt_lux.pty.output_tail import OutputTail
from punt_lux.pty.snapshot_outbox import SnapshotOutbox
from punt_lux.pty.viewer_outbox import ViewerOutbox
from punt_lux.pty.viewer_size import ViewerSize
from punt_lux.wire.stream.frames import FrameKind


def test_the_tail_hands_back_bytes_in_order_across_chunks() -> None:
    tail = OutputTail(100)
    tail.push(b"abc")
    tail.push(b"de")
    assert (tail.take(2), tail.take(2), tail.take(2)) == (b"ab", b"c", b"de")
    assert len(tail) == 0


def test_the_tail_reports_when_more_bytes_would_pass_its_limit() -> None:
    tail = OutputTail(4)
    tail.push(b"abc")
    assert tail.overflows(2)
    assert not tail.overflows(1)


def test_a_snapshot_is_taken_in_pieces_until_none_is_left() -> None:
    snapshot = SnapshotOutbox()
    snapshot.load(b"abcde")
    assert snapshot.take(3) == b"abc"
    assert len(snapshot) == 2
    assert snapshot.take(9) == b"de"
    assert not snapshot


def test_close_is_owed_once() -> None:
    notice = CloseNotice()
    assert notice.take(1) == []
    notice.set("exited", 0)
    assert [f.kind for f in notice.take(1)] == [FrameKind.CLOSE]
    assert notice.sent
    assert notice.take(1) == []


def test_close_waits_while_a_resync_is_pending() -> None:
    outbox = ViewerOutbox(1)
    outbox.finish("exited", 0)
    assert outbox.drain(CreditWindow(), resyncing=True) == []
    assert not outbox.close_sent
    assert [f.kind for f in outbox.drain(CreditWindow(), resyncing=False)] == [
        FrameKind.CLOSE
    ]


def test_the_snapshot_start_frame_precedes_the_snapshot() -> None:
    outbox = ViewerOutbox(7)
    outbox.begin(b"screen", b'{"k":1}')
    kinds = [f.kind for f in outbox.drain(CreditWindow(), resyncing=False)]
    assert kinds == [FrameKind.SNAPSHOT_START, FrameKind.SNAPSHOT]


def test_a_viewer_size_remembers_what_was_asked_and_what_it_got() -> None:
    size = ViewerSize()
    assert size.wanted == size.actual == (80, 24)
    size.want((100, 30))
    size.measured((90, 28))
    assert (size.wanted, size.actual) == ((100, 30), (90, 28))
