"""SO_SNDTIMEO bounds a send to a stuck peer within its time limit.

The packed timeval does not mean the same real limit on every platform, so the
contract is the measured behaviour, not the number: fill a send buffer against a
peer that never reads and prove the send fails within about 2.5 seconds. The
slow probe measures that; a fast unit test proves the option is applied.
"""

from __future__ import annotations

import socket
import struct
import time

import pytest

from punt_lux.send_timeout import SEND_TIMEOUT_PACKED, set_send_timeout

# The kernel may round or double the packed value; 2.5 s leaves headroom over the
# ~1-2 s the one-second timeval produces on macOS and Linux without flaking.
_CEILING_SECONDS = 2.5


def test_set_send_timeout_applies_the_option() -> None:
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        set_send_timeout(a)
        # The option reads back as the packed value, and the socket stays
        # blocking (a full buffer surfaces as BlockingIOError, not TimeoutError).
        applied = a.getsockopt(
            socket.SOL_SOCKET, socket.SO_SNDTIMEO, len(SEND_TIMEOUT_PACKED)
        )
        assert struct.unpack("ll", applied)[0] > 0
        assert a.gettimeout() is None
    finally:
        a.close()
        b.close()


@pytest.mark.slow
def test_a_send_to_a_never_reading_peer_fails_within_the_ceiling() -> None:
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        set_send_timeout(a)
        payload = b"x" * 65536  # b never reads, so a's send buffer fills
        start = time.monotonic()
        with pytest.raises(BlockingIOError):
            while True:
                a.sendall(payload)
        elapsed = time.monotonic() - start
        assert elapsed <= _CEILING_SECONDS, f"send blocked {elapsed:.2f}s"
    finally:
        a.close()
        b.close()
