"""A dial over a real ``SSLSocket``: frames, retirement and a wedged sender.

The cross-host leg (DES-090) dials over mutual TLS, and a TLS socket differs from
an ``AF_UNIX`` one where this design leans on it: ``select`` watches the descriptor
and not the SSL buffer, a concurrent read and write are not allowed, and ``shutdown``
must be the raw socket's (``unwrap`` blocks on a wedged peer). These tests run the
same dial code over a real mTLS loopback pair.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.protocol import PingMessage, QueryRequest, QueryResponse, ReadyMessage
from tests.display._mtls_harness import MtlsMaterial
from tests.domain.display_double import Call, Peer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_HOST = "display.example.com"


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
    connection = DisplayConnection(tls, 5.0)
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


def test_retiring_a_dial_releases_a_sender_wedged_on_a_tls_socket(
    tls: _TlsDisplay,
) -> None:
    connection = DisplayConnection(tls, 5.0)
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

    began = time.monotonic()
    assert connection.close_if_current(generation, cause="hub")
    sender.join(5.0)

    assert not sender.is_alive()
    assert outcome
    assert time.monotonic() - began < 5.0, (
        "shutdown, not an unwrap that waits on the peer"
    )
