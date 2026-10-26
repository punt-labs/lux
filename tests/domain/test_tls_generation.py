"""A dial over a real ``SSLSocket``: frames, retirement and a wedged sender.

The cross-host leg (DES-090) dials over mutual TLS, and a TLS socket differs from
an ``AF_UNIX`` one where this design leans on it: ``select`` watches the descriptor
and not the SSL buffer, a concurrent read and write are not allowed, and ``shutdown``
must be the raw socket's (``unwrap`` blocks on a wedged peer). These tests run the
same dial code over a real mTLS loopback pair.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import ssl
import threading
import time
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.domain.hub import bounded_ask
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.protocol import (
    AckMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    SceneMessage,
    TextElement,
)
from punt_lux.send_timeout import (
    SCENE_WRITE_DEADLINE_SECONDS,
    SEND_TIMEOUT_CEILING_SECONDS,
)
from tests.display._mtls_harness import MtlsMaterial
from tests.domain.display_double import Call, Peer
from tests.domain.test_retire_cause import _scene
from tests.link_access import (
    bare_connection,
    deaths_of,
    generation_of,
    no_reader,
    writer_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from punt_lux.domain.hub.dial_generation import DialGeneration

_HOST = "display.example.com"
# Scheduling slack on top of D: the deadline is a ceiling, not an alarm clock.
_MARGIN = 1.5


@final
class _TlsDisplay:
    """A dialer over a fresh mTLS loopback pair per dial."""

    _material: MtlsMaterial
    peers: list[Peer]
    _keep: list[socket.socket]

    def __new__(cls, scratch: Path) -> Self:
        self = super().__new__(cls)
        self._material = MtlsMaterial(scratch)
        self.peers = []
        self._keep = []
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        server_ctx = self._material.server_context()
        client_ctx = self._material.trusted_client_context(_HOST)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        accepted: list[ssl.SSLSocket] = []

        def accept() -> None:
            conn, _ = listener.accept()
            accepted.append(server_ctx.wrap_socket(conn, server_side=True))

        acceptor = threading.Thread(target=accept, daemon=True)
        acceptor.start()
        client = client_ctx.wrap_socket(
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        )
        client.connect(listener.getsockname())
        acceptor.join(5.0)
        listener.close()
        self.peers.append(Peer(accepted[0]))
        self._keep.append(accepted[0])
        return HandshakeResult(sock=client, endpoint="tls", ready=ReadyMessage())

    @property
    def peer(self) -> Peer:
        return self.peers[-1]

    def close(self) -> None:
        for sock in self._keep:
            sock.close()


@pytest.fixture
def tls(tmp_path: Path) -> Iterator[_TlsDisplay]:
    display = _TlsDisplay(tmp_path)
    yield display
    display.close()


def test_a_frame_goes_each_way_over_the_tls_dial(tls: _TlsDisplay) -> None:
    connection = DisplayConnection(tls, 5.0, ask_settle=no_reader)
    connection.open()
    generation = connection.require()
    try:
        generation.send(PingMessage(ts=1.0))
        assert tls.peer.read(1) == [PingMessage(ts=1.0)]

        tls.peer.send(QueryResponse(method="m", result={"n": 1}))
        chunk = generation.poll_chunk(3.0)

        assert chunk is not None
        assert list(generation.messages(chunk)) == [
            QueryResponse(method="m", result={"n": 1})
        ]
    finally:
        connection.close()


def test_a_reply_larger_than_one_tls_record_is_read_whole_inline(
    tls: _TlsDisplay,
) -> None:
    link = DisplayLink(tls, recv_timeout=5.0)
    link.connect()
    big = QueryResponse(method="m", result={"blob": "x" * 200_000})
    querying = Call(lambda: link.desk.asks().query("m", timeout=5.0))
    assert isinstance(tls.peer.read(1)[0], QueryRequest)

    tls.peer.send(big)

    assert querying.wait(5.0)
    assert querying.result == big
    link.close()


def test_a_tls_end_of_file_that_follows_queued_acks_is_read_then_the_displays_end(
    tls: _TlsDisplay, caplog: pytest.LogCaptureFixture
) -> None:
    """O-eof over TLS: the drain reads the ack a closing display left, then its end.

    The display reads the scene, queues an ack and closes with nothing of the Hub's
    unread, so TCP sends a FIN after the ack. The TLS stack delivers that as a plain
    end of file (a ragged one, with no ``close_notify``, which Python reads as an
    empty chunk), not a reset: the drain reads the ack first, and the empty chunk
    that follows is the display's end, so the acked scene is never charged.
    """
    link = DisplayLink(tls, recv_timeout=3.0)
    link.connect()
    generation = generation_of(link)
    writer_of(link).send_scene(_scene("a"))
    tls.peer.read(1)  # the display read it: nothing of the Hub's is left unread
    tls.peer.send(AckMessage(scene_id="a"))  # queued toward the Hub
    tls.peer.close()

    with caplog.at_level(logging.DEBUG):
        link.close()

    assert generation.owed_acks == 0  # the ack was read before the end
    assert generation.ended == "display"  # and the end was the display's
    assert not any("cut short" in r.getMessage() for r in caplog.records)
    assert deaths_of(link) == ()


def test_a_tls_reset_is_the_displays_end_though_it_may_discard_a_queued_ack(
    tls: _TlsDisplay, caplog: pytest.LogCaptureFixture
) -> None:
    """O-eof over TLS, the reset leg: the end is the display's, never the Hub's.

    The display closes with the scene unread, so TCP sends a reset, which the TLS
    stack raises as ``ConnectionResetError``: the drain reports the end as cut short.
    A reset from a remote peer may discard what was queued behind it (on Linux the
    ack here is lost, which the drain's own contract names as the cross-host
    carve-out), so the test pins only what holds on every stack: the end is
    recorded as the display's, and a death, if one is charged, is the display's.
    """
    link = DisplayLink(tls, recv_timeout=3.0)
    link.connect()
    generation = generation_of(link)
    writer_of(link).send_scene(_scene("a"))  # the display never reads it
    tls.peer.send(AckMessage(scene_id="a"))  # queued toward the Hub
    tls.peer.close()  # closed with the scene unread: a reset

    with caplog.at_level(logging.DEBUG):
        link.close()

    assert generation.ended == "display"
    assert any("cut short" in r.getMessage() for r in caplog.records)
    # A reset from a remote peer may have discarded acks: it is a warning.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("remote display" in r.getMessage() for r in warnings)
    assert {death.cause for death in deaths_of(link)} <= {"display"}


def test_retiring_a_dial_releases_a_sender_wedged_on_a_tls_socket(
    tls: _TlsDisplay,
) -> None:
    connection = bare_connection(tls, 5.0)
    connection.open()
    generation = connection.require()
    blob = QueryRequest(method="x", params={"blob": "x" * (15 * 1024 * 1024)})
    outcome: list[BaseException] = []

    def wedge() -> None:
        try:
            generation.send(blob)
        except OSError as exc:
            outcome.append(exc)

    sender = threading.Thread(target=wedge, daemon=True)
    sender.start()
    sender.join(0.5)
    assert sender.is_alive(), "the display reads nothing, so the write wedges"

    # A wedged writer holds the socket lock, so the settle's drain waits the ceiling
    # and the bound then captures it, whose shutdown frees the writer. An unwrap that
    # waited on the peer would not end at all.
    settle = SEND_TIMEOUT_CEILING_SECONDS + bounded_ask.SETTLE_BOUND
    began = time.monotonic()
    assert connection.retire(generation, cause="hub")
    sender.join(settle + 3.0)

    assert not sender.is_alive()
    assert outcome
    assert time.monotonic() - began < settle + 3.0, (
        "shutdown, not an unwrap that waits on the peer"
    )


_BIG = 11 << 20  # more than any socket buffer holds, under the wire size cap


def _big_scene() -> SceneMessage:
    return ScenePresentation(frame_id="big").message(
        "big", [TextElement(id="t", content="x" * _BIG)]
    )


def _a_tls_peer_that_never_reads(generation: DialGeneration) -> None:
    """Make every send on the dial's TLS socket report that it would block.

    That is all a peer that never reads shows the writer once the send buffer is full,
    and it leaves no scene write in flight: the next write, whatever it is, stalls.
    """
    sock = generation._socket._dial.sock  # test seam: the dial's own TLS socket

    def would_block(*_args: object) -> int:
        msg = "the send buffer is full"
        raise ssl.SSLWantWriteError(msg)

    sock.send = would_block  # type: ignore[method-assign]


class TestABoundedWrite:
    """Every write ends within D on either transport, by one user-space deadline.

    The dial's end is recorded at the deadline; these connections settle nothing (the
    settle's own drain is another matter, and these tests do not wait on it).
    """

    def test_p25_a_tls_peer_that_never_reads_ends_the_write_within_the_deadline(
        self, tls: _TlsDisplay
    ) -> None:
        connection = DisplayConnection(tls, 5.0, ask_settle=no_reader)
        connection.open()
        generation = connection.require()

        began = time.monotonic()
        with pytest.raises(OSError):
            generation.send_scene(_big_scene())
        took = time.monotonic() - began

        assert took < SCENE_WRITE_DEADLINE_SECONDS + _MARGIN
        assert generation.ended == "unresponsive"

    def test_p25_a_slow_draining_tls_peer_ends_the_write_within_the_deadline(
        self, tls: _TlsDisplay
    ) -> None:
        connection = DisplayConnection(tls, 5.0, ask_settle=no_reader)
        connection.open()
        generation = connection.require()
        peer_sock = tls.peer.raw
        stop = threading.Event()

        def drain_slowly() -> None:
            while not stop.is_set():
                with contextlib.suppress(OSError):
                    peer_sock.recv(65536)
                stop.wait(0.2)  # slower than the writer, but never stopped

        draining = threading.Thread(target=drain_slowly, daemon=True)
        draining.start()
        try:
            began = time.monotonic()
            with pytest.raises(OSError):
                generation.send_scene(_big_scene())
            took = time.monotonic() - began
        finally:
            stop.set()
            draining.join(2.0)

        assert took < SCENE_WRITE_DEADLINE_SECONDS + _MARGIN
        assert generation.ended == "unresponsive"

    def test_p25_a_keepalive_ping_that_is_the_first_write_to_stall_ends_the_dial(
        self, tls: _TlsDisplay
    ) -> None:
        connection = DisplayConnection(tls, 5.0, ask_settle=no_reader)
        connection.open()
        generation = connection.require()
        tls.peer.send(PongMessage(ts=0.0))  # the post-handshake records, then a frame
        assert generation.poll_chunk(3.0) is not None
        _a_tls_peer_that_never_reads(generation)  # no scene write in flight

        began = time.monotonic()
        with pytest.raises(OSError):
            generation.send_ping(1.0)
        took = time.monotonic() - began

        assert took < SCENE_WRITE_DEADLINE_SECONDS + _MARGIN
        assert generation.ended == "unresponsive"
