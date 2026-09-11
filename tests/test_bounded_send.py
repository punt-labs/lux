"""Unit tests for punt_lux.bounded_send — backpressure vs dead peer."""

from __future__ import annotations

import errno
import socket
import ssl
import time
from typing import cast

import pytest

from punt_lux.bounded_send import BoundedSend, TornStreamError


class _FakeSocket:
    """A socket stand-in whose ``send`` yields EAGAIN, chunks, or a dead peer.

    ``eagain_before`` would-blocks precede real progress; each accepting ``send``
    takes at most ``chunk`` bytes so partial-write resumption is exercised.
    ``block_after`` (set for the torn-stream case) would-blocks forever once that
    many bytes have been accepted. ``returns_zero`` accepts nothing (a broken
    stream socket). A ``fail_with`` error is raised instead. ``calls`` counts sends.
    """

    _eagain_left: int
    _chunk: int
    _block_after: int | None
    _returns_zero: bool
    _fail_with: OSError | None
    _want_read_left: int
    sent: bytearray
    calls: int

    def __new__(
        cls,
        *,
        eagain_before: int = 0,
        chunk: int = 1 << 30,
        block_after: int | None = None,
        returns_zero: bool = False,
        fail_with: OSError | None = None,
        want_read_before: int = 0,
    ) -> _FakeSocket:
        self = super().__new__(cls)
        self._eagain_left = eagain_before
        self._chunk = chunk
        self._block_after = block_after
        self._returns_zero = returns_zero
        self._fail_with = fail_with
        self._want_read_left = want_read_before
        self.sent = bytearray()
        self.calls = 0
        return self

    def send(self, data: memoryview) -> int:
        self.calls += 1
        if self._fail_with is not None:
            raise self._fail_with
        if self._returns_zero:
            return 0
        if self._want_read_left > 0:
            self._want_read_left -= 1
            raise ssl.SSLWantReadError
        if self._eagain_left > 0:
            self._eagain_left -= 1
            raise BlockingIOError(errno.EAGAIN, "resource temporarily unavailable")
        if self._block_after is not None and len(self.sent) >= self._block_after:
            raise BlockingIOError(errno.EAGAIN, "would block after a partial write")
        take = min(len(data), self._chunk)
        if self._block_after is not None:
            take = min(take, self._block_after - len(self.sent))
        self.sent.extend(bytes(data[:take]))
        return take

    def fileno(self) -> int:
        return -1


def _patch_writable(monkeypatch: pytest.MonkeyPatch, *, writable: bool) -> None:
    """Force ``select`` inside bounded_send to report writability (or not)."""

    def fake_select(
        _r: list[object], w: list[object], _x: list[object], _t: float
    ) -> tuple[list[object], list[object], list[object]]:
        return ([], list(w) if writable else [], [])

    monkeypatch.setattr("punt_lux.bounded_send.select.select", fake_select)


def _patch_writable_never_readable(
    monkeypatch: pytest.MonkeyPatch, select_calls: list[float]
) -> None:
    """Force ``select`` to report writable but never readable, recording each
    call's timeout -- the exact scenario a direction-unaware wait busy-spins
    on: the send buffer has room, but nothing to read yet.
    """

    def fake_select(
        _r: list[object], w: list[object], _x: list[object], t: float
    ) -> tuple[list[object], list[object], list[object]]:
        select_calls.append(t)
        return ([], list(w), [])  # writable always true, readable never

    monkeypatch.setattr("punt_lux.bounded_send.select.select", fake_select)


def _patch_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``select`` to report both directions ready."""

    def fake_select(
        r: list[object], w: list[object], _x: list[object], _t: float
    ) -> tuple[list[object], list[object], list[object]]:
        return (list(r), list(w), [])

    monkeypatch.setattr("punt_lux.bounded_send.select.select", fake_select)


class TestBackpressure:
    """A would-block is waited out and the message still lands, in order."""

    def test_eagain_then_drains(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_writable(monkeypatch, writable=True)
        sock = _FakeSocket(eagain_before=3)
        payload = b"hello world" * 5
        BoundedSend().send(cast("socket.socket", sock), payload, time.monotonic() + 1.0)
        assert bytes(sock.sent) == payload

    def test_partial_writes_resume_from_offset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_writable(monkeypatch, writable=True)
        # Small chunks interleaved with would-blocks: the offset must advance
        # across both so the framed bytes arrive contiguous, never re-sent.
        sock = _FakeSocket(eagain_before=2, chunk=4)
        payload = bytes(range(37))
        BoundedSend().send(cast("socket.socket", sock), payload, time.monotonic() + 1.0)
        assert bytes(sock.sent) == payload


class TestWantReadDuringSend:
    """``SSLWantReadError`` waits on readability, never busy-spins on writability.

    A TLS 1.3 post-handshake event (NewSessionTicket/KeyUpdate) can make
    ``send()`` want a read before it can finish -- a normal event, not
    malice. Waiting on the wrong fd-set (writability, which is usually
    already true -- the kernel send buffer has room) would make ``select``
    return instantly every time, so the loop retries as fast as the CPU
    allows: a busy-spin for the whole deadline.
    """

    def test_never_readable_gives_up_after_one_attempt_not_a_spin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        select_calls: list[float] = []
        _patch_writable_never_readable(monkeypatch, select_calls)
        sock = _FakeSocket(want_read_before=1_000_000)  # never stops wanting a read
        with pytest.raises(BlockingIOError):
            BoundedSend().send(
                cast("socket.socket", sock), b"payload", time.monotonic() + 5.0
            )
        # A direction-unaware wait would retry on every instantly-writable
        # select() -- hundreds of calls in the time this test takes to run.
        # Waiting on readability instead means exactly one send, one wait,
        # one give-up: the peer never became readable, so nothing to retry.
        assert sock.calls == 1
        assert len(select_calls) == 1
        assert bytes(sock.sent) == b""  # nothing reached the wire

    def test_resumes_once_readable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_readable(monkeypatch)
        sock = _FakeSocket(want_read_before=1)
        payload = b"hello world"
        BoundedSend().send(cast("socket.socket", sock), payload, time.monotonic() + 1.0)
        assert bytes(sock.sent) == payload
        assert sock.calls == 2  # one want-read, one successful send


class TestGiveUp:
    """At the deadline, a clean would-block defers but a partial write severs."""

    def test_untouched_frame_reraises_blocking(self) -> None:
        # Deadline already past and nothing written: a clean would-block. The
        # frame never reached the wire, so BlockingIOError lets the caller defer.
        sock = _FakeSocket(eagain_before=1_000_000)
        with pytest.raises(BlockingIOError):
            BoundedSend().send(
                cast("socket.socket", sock), b"payload", time.monotonic() - 1.0
            )
        assert bytes(sock.sent) == b""  # nothing was delivered

    def test_partial_write_at_deadline_raises_torn_stream(self) -> None:
        # Some bytes went out, then the peer blocks past the deadline: the stream
        # now carries half a frame and can never be finished. TornStreamError
        # (an OSError) tells the caller to sever, never reuse the torn stream.
        sock = _FakeSocket(chunk=4, block_after=4)
        with pytest.raises(TornStreamError):
            BoundedSend().send(
                cast("socket.socket", sock),
                b"a much longer frame",
                time.monotonic() - 1.0,
            )
        assert len(sock.sent) == 4  # a partial frame is stranded on the wire
        assert not isinstance(TornStreamError(), BlockingIOError)  # never "defer"


class TestDeadPeer:
    """A dead-peer OSError propagates immediately, unbounded."""

    def test_broken_pipe_propagates(self) -> None:
        sock = _FakeSocket(fail_with=BrokenPipeError(errno.EPIPE, "broken pipe"))
        with pytest.raises(BrokenPipeError):
            BoundedSend().send(
                cast("socket.socket", sock), b"payload", time.monotonic() + 1.0
            )

    def test_zero_byte_send_raises_without_spinning(self) -> None:
        # A stream socket that accepts 0 bytes is broken: without this the loop
        # would tight-spin forever (offset never advances). It must raise at once.
        sock = _FakeSocket(returns_zero=True)
        with pytest.raises(OSError, match="zero bytes"):
            BoundedSend().send(
                cast("socket.socket", sock), b"payload", time.monotonic() + 1.0
            )
        assert sock.calls == 1  # raised on the first send, never looped
