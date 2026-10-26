"""A dial over a real ``SSLSocket``: frames, retirement and a wedged sender.

The cross-host leg (DES-090) dials over mutual TLS, and a TLS socket differs from
an ``AF_UNIX`` one where this design leans on it: ``select`` watches the descriptor
and not the SSL buffer, a concurrent read and write are not allowed, and ``shutdown``
must be the raw socket's (``unwrap`` blocks on a wedged peer). These tests run the
same dial code over a real mTLS loopback pair.
"""

from __future__ import annotations

import logging
import socket
import ssl
import threading
import time
from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.domain.hub import bounded_ask, socket_line
from punt_lux.domain.hub.connection_closed import UnresponsiveError
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.drain_result import Drained
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
from tests.domain.display_double import Call, Display, Peer, until
from tests.domain.test_retire_cause import _linked, _scene
from tests.link_access import (
    bare_connection,
    count_end_records,
    deaths_of,
    generation_of,
    no_reader,
    writer_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
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
        chunk = None
        for _ in range(30):  # a poll that finds only post-handshake records is None
            chunk = generation.poll_chunk(0.2)
            if chunk is not None:
                break

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


def _a_tls_peer_that_trickles(generation: DialGeneration, every: float) -> None:
    """Make the dial's TLS socket take 8 KiB each ``every`` seconds, else would block.

    A slow peer that never stops: some bytes go in every ``every`` seconds, so no gap
    anywhere comes near ``D``. Faked at the socket, because a real TLS write shows no
    byte to the sender until a whole record is out, and a real slow peer on loopback
    stalls in the kernel for longer than any ``D`` a test can afford.
    """
    sock = generation._socket._dial.sock  # test seam: the dial's own TLS socket
    last = [time.monotonic()]

    def trickle(*args: object) -> int:
        if time.monotonic() - last[0] < every:
            time.sleep(0.01)  # the select on a writable socket would spin
            msg = "the send buffer is full"
            raise ssl.SSLWantWriteError(msg)
        last[0] = time.monotonic()
        return min(len(cast("memoryview", args[0])), 8 << 10)

    sock.send = trickle  # type: ignore[method-assign]


_BOUND = SEND_TIMEOUT_CEILING_SECONDS + bounded_ask.SETTLE_BOUND  # the settle's bound


def _ends_within(limit: float, action: Callable[[], object]) -> tuple[float, object]:
    """Run ``action`` on its own thread; how long it took, and what it raised.

    A rule that is broken fails here with a message, not by hanging the harness.
    """
    began = time.monotonic()
    call = Call(action)
    assert call.wait(limit), f"the action did not end within {limit}s"
    return time.monotonic() - began, call.error


class TestABoundedWrite:
    """Every write ends within D on either transport, by one user-space deadline.

    The dial's end is recorded at the deadline and the dial is settled within the
    settle's bound: the settle's own drain never waits.
    """

    def test_p25_a_tls_peer_that_never_reads_ends_the_write_within_the_deadline(
        self, tls: _TlsDisplay, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = count_end_records(monkeypatch)
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()

        took, error = _ends_within(_BOUND, lambda: generation.send_scene(_big_scene()))

        assert isinstance(error, UnresponsiveError)
        assert took < SCENE_WRITE_DEADLINE_SECONDS + _MARGIN
        assert generation.ended == "unresponsive"
        assert until(lambda: generation.is_settled, _BOUND)
        assert records.count(True) == 1  # the cause is recorded once

    def test_p29_a_slow_but_steady_tls_peer_keeps_its_write(
        self, tls: _TlsDisplay, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No gap of ``D`` anywhere, so the write that takes many ``D`` is not cut."""
        window = 0.3
        monkeypatch.setattr(socket_line, "SCENE_WRITE_DEADLINE_SECONDS", window)
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        scene = ScenePresentation(frame_id="steady").message(
            "steady", [TextElement(id="t", content="x" * (512 << 10))]
        )

        _a_tls_peer_that_trickles(generation, every=0.1)

        took, error = _ends_within(30.0, lambda: generation.send_scene(scene))

        assert error is None
        assert took > 3 * window  # the premise: the write outlasted the window
        assert generation.ended is None
        assert generation.owed_acks == 1  # the scene is in the ledger
        connection.close()

    def test_p27_a_keepalive_ping_that_is_the_first_write_to_stall_ends_the_dial(
        self, tls: _TlsDisplay, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = count_end_records(monkeypatch)
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        _a_tls_peer_that_never_reads(generation)  # no scene write in flight

        took, error = _ends_within(_BOUND, lambda: generation.send_ping(1.0))

        assert isinstance(error, UnresponsiveError)
        assert took < SCENE_WRITE_DEADLINE_SECONDS + _MARGIN
        assert generation.ended == "unresponsive"
        assert until(lambda: generation.is_settled, _BOUND)
        assert records.count(True) == 1
        line = generation._socket._line  # test seam: the socket's own line
        assert line.acquire_within(1.0), "the lock was kept"
        line.release()

    def test_p27_a_query_that_is_the_first_write_to_stall_ends_the_dial(
        self, tls: _TlsDisplay, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = count_end_records(monkeypatch)
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        _a_tls_peer_that_never_reads(generation)

        took, error = _ends_within(
            _BOUND, lambda: generation.send_query(QueryRequest(method="m"))
        )

        assert isinstance(error, UnresponsiveError)
        assert took < SCENE_WRITE_DEADLINE_SECONDS + _MARGIN
        assert generation.ended == "unresponsive"
        assert until(lambda: generation.is_settled, _BOUND)
        assert records.count(True) == 1
        line = generation._socket._line  # test seam: the socket's own line
        assert line.acquire_within(1.0), "the lock was kept"
        line.release()


class TestTheDrainNeverWaits:
    """B2: on TLS, a readable descriptor is not an application byte."""

    def test_a_drain_with_only_post_handshake_records_pending_returns_nothing(
        self, tls: _TlsDisplay
    ) -> None:
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()  # the session tickets sit unread

        took, error = _ends_within(3.0, generation.drain)

        assert error is None
        assert generation.drain() == Drained(b"", ended=False)
        assert took < 1.0

    def test_an_ack_queued_behind_those_records_is_not_lost(
        self, tls: _TlsDisplay
    ) -> None:
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        tls.peer.send(AckMessage(scene_id="a"))  # behind the tickets
        taken = bytearray()

        def looks_until_the_ack_arrives() -> bool:
            # A look that finds nothing yet is no loss: the ack stays in the socket.
            look = generation.drain()
            assert look.ended is False
            taken.extend(look.chunk)
            return bool(taken)

        _, error = _ends_within(5.0, lambda: until(looks_until_the_ack_arrives, 4.0))

        assert error is None
        assert list(generation.messages(bytes(taken))) == [AckMessage(scene_id="a")]

    def test_a_poll_with_only_post_handshake_records_pending_waits_for_nothing(
        self, tls: _TlsDisplay
    ) -> None:
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()  # the session tickets sit unread

        polling = Call(lambda: generation.poll_chunk(1.0))

        assert polling.wait(4.0), "the poll waited for an application byte"
        assert polling.result is None

    def test_a_poll_still_returns_a_frame_that_follows_those_records(
        self, tls: _TlsDisplay
    ) -> None:
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        tls.peer.send(PongMessage(ts=2.0))
        taken = bytearray()

        def polls_until_the_frame_arrives() -> bool:
            chunk = generation.poll_chunk(0.2)
            taken.extend(chunk or b"")
            return bool(taken)

        _, error = _ends_within(6.0, lambda: until(polls_until_the_frame_arrives, 4.0))

        assert error is None
        assert list(generation.messages(bytes(taken))) == [PongMessage(ts=2.0)]


def test_a_tls_dial_reaches_another_host_and_names_how_it_ended(
    tls: _TlsDisplay,
) -> None:
    connection = bare_connection(tls, 5.0)
    connection.open()
    generation = connection.require()
    try:
        assert (generation.ref.is_cross_host, generation.ref.ended) == (True, None)

        generation.end("unresponsive")

        assert generation.ref.ended == "unresponsive"
    finally:
        connection.close()


def test_a_local_dial_does_not_reach_another_host() -> None:
    display = Display()
    try:
        link = _linked(display, listening=False)

        assert generation_of(link).ref.is_cross_host is False
    finally:
        display.close()


class TestAReadThatNeedsToWriteIsNotTheDisplaysEnd:
    """A TLS read may need to write (a key update); with a full send buffer it waits."""

    def test_a_poll_that_wants_to_write_finds_nothing_not_the_displays_end(
        self, tls: _TlsDisplay, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        _wants_to_write(monkeypatch)

        polling = Call(lambda: generation.poll_chunk(0.5))

        assert polling.wait(4.0), "the poll did not end"
        assert polling.result is None
        assert generation.ended is None

    def test_a_drain_that_wants_to_write_is_not_the_end_of_the_stream(
        self, tls: _TlsDisplay, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = bare_connection(tls, 5.0)
        connection.open()
        generation = connection.require()
        tls.peer.send(AckMessage(scene_id="a"))
        _wants_to_write(monkeypatch)

        looking = Call(generation.drain)

        assert looking.wait(4.0), "the drain did not end"
        assert looking.result == Drained(b"", ended=False)


def _wants_to_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the Hub's dialed TLS socket report that its next read needs to write."""
    real = ssl.SSLSocket.recv

    def recv(this: ssl.SSLSocket, buflen: int = 1024, flags: int = 0) -> bytes:
        if this.server_side:
            return real(this, buflen, flags)
        raise ssl.SSLWantWriteError("the read needs to write first")

    monkeypatch.setattr(ssl.SSLSocket, "recv", recv)
