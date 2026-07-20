"""Bound every socket send so a wedged peer cannot block the sender forever.

A display that stops reading fills the kernel send buffer; a send with no time
limit then waits forever, which is how one MCP ``clear`` once froze an agent for
38 minutes. ``SO_SNDTIMEO`` puts a ceiling on the wait.

The packed value and the real limit it produces differ by platform, so the
number here is not the contract — the measured limit is, which the probe test
pins. ``struct.pack("ll", 1, 0)`` is a 16-byte ``timeval`` of one second; macOS
applies double the value (two seconds) and rejects the 12-byte form, while Linux
takes it at face value (one second). Both stay under the 2.5-second ceiling the
probe asserts.

Setting the option leaves the socket in blocking mode as far as CPython is
concerned — ``gettimeout()`` still returns ``None`` — so a full buffer surfaces
as ``BlockingIOError`` (``EWOULDBLOCK``), never ``TimeoutError``. Nothing in this
path ever makes the socket non-blocking, so ``BlockingIOError`` unambiguously
means "the send hit its time limit," which is safe to key on.
"""

from __future__ import annotations

import socket
import struct

__all__ = ["SEND_TIMEOUT_PACKED", "set_send_timeout"]

SEND_TIMEOUT_PACKED = struct.pack("ll", 1, 0)


def set_send_timeout(sock: socket.socket) -> None:
    """Apply the bounded-send time limit to ``sock`` via ``SO_SNDTIMEO``."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, SEND_TIMEOUT_PACKED)
