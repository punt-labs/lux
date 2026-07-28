"""Unit tests for punt_lux.bounded_send — backpressure vs dead peer."""

from __future__ import annotations

import errno
import socket
import time
from typing import cast

import pytest

from punt_lux.bounded_send import BoundedSend


class _FakeSocket:
    """A socket stand-in whose ``send`` yields EAGAIN, chunks, or a dead peer.

    ``eagain_before`` would-blocks precede real progress; each accepting ``send``
    takes at most ``chunk`` bytes so partial-write resumption is exercised. A
    ``fail_with`` error (set for the dead-peer case) is raised instead of blocking.
    """

    _eagain_left: int
    _chunk: int
    _fail_with: OSError | None
    sent: bytearray

    def __new__(
        cls,
        *,
        eagain_before: int = 0,
        chunk: int = 1 << 30,
        fail_with: OSError | None = None,
    ) -> _FakeSocket:
        self = super().__new__(cls)
        self._eagain_left = eagain_before
        self._chunk = chunk
        self._fail_with = fail_with
        self.sent = bytearray()
        return self

    def send(self, data: memoryview) -> int:
        if self._fail_with is not None:
            raise self._fail_with
        if self._eagain_left > 0:
            self._eagain_left -= 1
            raise BlockingIOError(errno.EAGAIN, "resource temporarily unavailable")
        take = min(len(data), self._chunk)
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


class TestGiveUp:
    """A peer still unwritable at the deadline raises BlockingIOError."""

    def test_past_deadline_reraises_blocking(self) -> None:
        # A deadline already in the past: the first would-block gives up at once,
        # no waiting, so the give-up is deterministic without touching the clock.
        sock = _FakeSocket(eagain_before=1_000_000)
        with pytest.raises(BlockingIOError):
            BoundedSend().send(
                cast("socket.socket", sock), b"payload", time.monotonic() - 1.0
            )
        assert bytes(sock.sent) == b""  # nothing was delivered


class TestDeadPeer:
    """A dead-peer OSError propagates immediately, unbounded."""

    def test_broken_pipe_propagates(self) -> None:
        sock = _FakeSocket(fail_with=BrokenPipeError(errno.EPIPE, "broken pipe"))
        with pytest.raises(BrokenPipeError):
            BoundedSend().send(
                cast("socket.socket", sock), b"payload", time.monotonic() + 1.0
            )
