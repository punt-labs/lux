"""Bound every socket send so a wedged peer cannot block the sender forever.

A display that stops reading fills the kernel send buffer; a send with no time
limit then waits forever, which is how one MCP ``clear`` once froze an agent for
38 minutes. Two bounds keep that from happening, and they bound different sends.

``SO_SNDTIMEO`` (``set_send_timeout``) bounds only the blocking send of the dial's
handshake, made before the dial is handed to its connection. Every write after it,
on either transport, is a user-space bounded send (``BoundedSend``) on a socket made
non-blocking for that write, under one deadline ``D``
(``SCENE_WRITE_DEADLINE_SECONDS``) that covers the wait for the dial's socket lock as
well. ``SO_SNDTIMEO`` bounds nothing on a TLS write at all.

The packed value and the real limit it produces differ by platform, so the
number here is not the contract -- the measured limit is, which the probe test
pins. ``struct.pack("ll", 1, 0)`` is a 16-byte ``timeval`` of one second; macOS
applies double the value (two seconds) and rejects the 12-byte form, while Linux
takes it at face value (one second). Both stay under the 2.5-second limit the
probe asserts (``SEND_TIMEOUT_PROBE_LIMIT_SECONDS``).

Setting the option leaves the socket in blocking mode as far as CPython is
concerned -- ``gettimeout()`` still returns ``None`` -- so a full buffer on the
handshake's send surfaces as ``BlockingIOError`` (``EWOULDBLOCK``), never
``TimeoutError``. ``BlockingIOError`` on a dial's write is the other bound's: the
deadline ``D`` passed with no byte sent, or the socket lock was not free in time.
Either ends the dial as unresponsive.
"""

from __future__ import annotations

import socket
import struct

__all__ = [
    "SCENE_WRITE_DEADLINE_SECONDS",
    "SEND_TIMEOUT_CEILING_SECONDS",
    "SEND_TIMEOUT_PACKED",
    "SEND_TIMEOUT_PROBE_LIMIT_SECONDS",
    "SEND_TIMEOUT_SECONDS",
    "set_send_timeout",
]

SEND_TIMEOUT_SECONDS = 1
SEND_TIMEOUT_PACKED = struct.pack("ll", SEND_TIMEOUT_SECONDS, 0)
# The longest a stalled send may take on any platform: the probe test asserts it.
SEND_TIMEOUT_PROBE_LIMIT_SECONDS = 2.5
# D: the deadline of one scene write, on either transport, and the longest a ping or
# a query waits for the socket lock. It is the probe's limit, so no write that
# completes today is cut short.
SCENE_WRITE_DEADLINE_SECONDS = SEND_TIMEOUT_PROBE_LIMIT_SECONDS
# How long a drain waits on a writer: strictly above D, so a writer that is still
# inside its deadline is always waited out, and one that breaks the deadline (which
# the write's own bound should make impossible) is left to the settle bound.
SEND_TIMEOUT_CEILING_SECONDS = SCENE_WRITE_DEADLINE_SECONDS + 1.0


def set_send_timeout(sock: socket.socket) -> None:
    """Apply the bounded-send time limit to ``sock`` via ``SO_SNDTIMEO``."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, SEND_TIMEOUT_PACKED)
