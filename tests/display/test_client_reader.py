"""Unit tests for ClientReader -- recv / TLS-drain / frame / dispatch.

The TLS-drain test drives a real ``ssl`` handshake over TCP loopback: it is
the one behavior a plain ``socket.socket`` cannot exercise, because
``pending()`` -- OpenSSL's decrypted-but-unread record buffer -- exists only
on an ``ssl.SSLSocket``. The remaining tests use fake sockets to exercise the
empty-recv, malformed-frame, and buffer-overflow removal paths deterministically.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Self, cast, final

from punt_lux.display.client_reader import ClientReader
from punt_lux.display.socket_listener_callbacks import SocketListenerCallbacks
from punt_lux.display.socket_server import SocketListener
from punt_lux.protocol import (
    FrameReader,
    SceneMessage,
    TextElement,
    encode_message,
)
from punt_lux.trust import CertificateAuthority


def _server_ctx(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    ctx = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.CLIENT_AUTH)
    key_pair, leaf = ca.issue_leaf("display.example.com")
    (tmp_path / "s.crt").write_bytes(leaf.to_pem())
    (tmp_path / "s.key").write_bytes(key_pair.to_pem())
    ctx.load_cert_chain(str(tmp_path / "s.crt"), str(tmp_path / "s.key"))
    return ctx


def _client_ctx(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    ctx = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    key_pair, leaf = ca.issue_leaf("hub1.example.com")
    (tmp_path / "c.crt").write_bytes(leaf.to_pem())
    (tmp_path / "c.key").write_bytes(key_pair.to_pem())
    ctx.load_cert_chain(str(tmp_path / "c.crt"), str(tmp_path / "c.key"))
    return ctx


def _capturing_listener() -> tuple[SocketListener, list[object]]:
    received: list[object] = []
    listener = SocketListener(
        SocketListenerCallbacks(
            on_message=lambda _sock, msg: received.append(msg),
            on_client_disconnected=lambda _fd: None,
            on_error=lambda _sev, _msg, _ctx: None,
        )
    )
    return listener, received


def _tls_pair(
    ca: CertificateAuthority, tmp_path: Path
) -> tuple[ssl.SSLSocket, ssl.SSLSocket, socket.socket]:
    """Return a connected (client, server) mTLS pair over TCP loopback."""
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    port = int(lsock.getsockname()[1])
    accepted: list[ssl.SSLSocket] = []

    def _accept() -> None:
        raw, _ = lsock.accept()
        accepted.append(_server_ctx(ca, tmp_path).wrap_socket(raw, server_side=True))

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    client = _client_ctx(ca, tmp_path).wrap_socket(
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    )
    client.connect(("127.0.0.1", port))
    thread.join(timeout=5.0)
    assert accepted, "server never completed the handshake"
    return client, accepted[0], lsock


class TestTlsDrain:
    def test_a_buffered_tls_record_is_drained_after_a_partial_recv(
        self, tmp_path: Path
    ) -> None:
        """prereq 3: a single decrypted TLS record can outlast the ``recv()``
        that started it -- OpenSSL buffers the remainder in ``pending()`` while
        the kernel fd goes select-quiet. ``recv(1)`` forces exactly that state
        (one atomic record decrypted, one byte returned, the rest buffered);
        the drain must then complete the frame with no further select wake-up.
        """
        ca = CertificateAuthority.create()
        client, srv, lsock = _tls_pair(ca, tmp_path)
        scene = SceneMessage(
            id="s", elements=[TextElement(id="t", content="hello")], frame_id="s"
        )
        wire = encode_message(scene)
        try:
            client.sendall(wire)
            time.sleep(0.2)  # the whole record reaches the server's kernel buffer

            reader = FrameReader()
            first = srv.recv(1)  # decrypts the record, returns 1 byte, buffers the rest
            assert len(first) == 1
            assert srv.pending() > 0, "the rest of the record must be buffered"
            reader.feed(first)

            ClientReader._drain_tls_backlog(srv, reader)

            drained = list(reader.drain_typed())
            assert [m.id for m in drained if isinstance(m, SceneMessage)] == ["s"]
        finally:
            client.close()
            srv.close()
            lsock.close()

    def test_a_plain_socket_is_left_untouched_by_the_drain(self) -> None:
        """The ``AF_UNIX`` leg has no ``pending()`` buffer -- the drain is a
        no-op on a plain ``socket.socket`` and must not attempt ``pending()``."""
        left, _right = socket.socketpair()
        try:
            reader = FrameReader()
            ClientReader._drain_tls_backlog(left, reader)  # must not raise
            assert reader.buffer_size == 0
        finally:
            left.close()
            _right.close()


@final
class _FakeSock:
    """A minimal socket stand-in for the non-TLS removal paths."""

    _fd: int
    _data: bytes
    _closed: bool

    def __new__(cls, fd: int, data: bytes) -> Self:
        self = super().__new__(cls)
        self._fd = fd
        self._data = data
        self._closed = False
        return self

    def recv(self, _bufsize: int) -> bytes:
        return self._data

    def fileno(self) -> int:
        return self._fd

    def close(self) -> None:
        self._closed = True


def _inject(listener: SocketListener, fake: _FakeSock) -> socket.socket:
    sock = cast("socket.socket", fake)
    listener.clients.append(sock)
    listener._registry.register_connection(fake.fileno(), sock)
    return sock


class TestRemovalPaths:
    def test_empty_recv_removes_the_client(self) -> None:
        listener, _ = _capturing_listener()
        sock = _inject(listener, _FakeSock(fd=501, data=b""))
        listener._reader.read(sock)
        assert sock not in listener.clients

    def test_a_full_frame_is_dispatched(self) -> None:
        listener, received = _capturing_listener()
        scene = SceneMessage(
            id="s", elements=[TextElement(id="t", content="hi")], frame_id="s"
        )
        sock = _inject(listener, _FakeSock(fd=502, data=encode_message(scene)))
        listener._reader.read(sock)
        assert [m.id for m in received if isinstance(m, SceneMessage)] == ["s"]

    def test_malformed_wire_data_removes_the_client(self) -> None:
        listener, _ = _capturing_listener()
        errors: list[str] = []
        listener = SocketListener(
            SocketListenerCallbacks(
                on_message=lambda _s, _m: None,
                on_client_disconnected=lambda _fd: None,
                on_error=lambda sev, _m, _c: errors.append(sev),
            )
        )
        # A valid 4-byte length header claiming a body, followed by junk that
        # cannot decode -- drain_typed raises and the client is dropped.
        bad = (5).to_bytes(4, "big") + b"\xff\xff\xff\xff\xff"
        sock = _inject(listener, _FakeSock(fd=503, data=bad))
        listener._reader.read(sock)
        assert sock not in listener.clients
