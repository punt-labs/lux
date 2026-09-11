"""Coexistence: one SocketListener serves AF_UNIX and cross-host TLS at once.

system.tex §"Coexistence with the Local Fast Path": both legs feed the same
socket-listener machinery -- once a TLS peer's handshake (including
client-certificate verification) completes, it converges onto the exact
same registration, ``select``, ``recv``, and dispatch path an ``AF_UNIX``
peer already uses. This is the one integration test that proves the two
legs share that machinery correctly in the same poll cycle, and that
neither leg regresses the other -- a same-host Hub keeps working exactly
as before, unaffected by whether cross-host is enabled alongside it.
"""

from __future__ import annotations

import socket
import ssl
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from punt_lux.display.cross_host_listener import CrossHostListener
from punt_lux.display.socket_listener_callbacks import SocketListenerCallbacks
from punt_lux.display.socket_server import SocketListener
from punt_lux.protocol import (
    ReadyMessage,
    SceneMessage,
    TextElement,
    recv_message,
    send_message,
)
from punt_lux.trust import CertificateAuthority

if TYPE_CHECKING:
    from punt_lux.protocol.messages import Message

# ---------------------------------------------------------------------------
# Helpers -- shared with test_cross_host_listener.py's mTLS setup
# ---------------------------------------------------------------------------


def _server_ssl_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.CLIENT_AUTH)
    key_pair, leaf = ca.issue_leaf("display.example.com")
    cert_path, key_path = tmp_path / "server.crt", tmp_path / "server.key"
    cert_path.write_bytes(leaf.to_pem())
    key_path.write_bytes(key_pair.to_pem())
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def _client_ssl_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    key_pair, cert = ca.issue_leaf("hub1.example.com")
    cert_path, key_path = tmp_path / "client.crt", tmp_path / "client.key"
    cert_path.write_bytes(cert.to_pem())
    key_path.write_bytes(key_pair.to_pem())
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _connect_tls_in_background(
    ctx: ssl.SSLContext, port: int
) -> tuple[threading.Thread, list[ssl.SSLSocket]]:
    """Connect a client TLS socket on a background thread; see
    ``test_cross_host_listener.py``'s identical helper for why."""
    result: list[ssl.SSLSocket] = []

    def _run() -> None:
        client = ctx.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        client.connect(("127.0.0.1", port))
        result.append(client)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread, result


def _drive_until_tls_ready(
    unix_listener: SocketListener,
    cross_host: CrossHostListener,
    *,
    rounds: int = 400,
) -> None:
    """Pump both legs together, promoting a verified TLS peer as it arrives.

    This is the render loop's own per-frame shape: accept the AF_UNIX leg,
    then pump the cross-host leg and register anything it hands back --
    exactly what a future render-loop integration point would do each frame.
    """
    for _ in range(rounds):
        unix_listener.accept_connections()
        cross_host.accept_pending()
        for tls_sock in cross_host.pump_ready():
            unix_listener.register_client(tls_sock)
            return  # the TLS peer just got promoted -- done
        time.sleep(0.005)  # give the client thread's connect+handshake a chance


class TestCoexistence:
    def test_af_unix_and_cross_host_clients_are_served_by_one_listener(
        self, tmp_path: Path
    ) -> None:
        # -- one SocketListener, both legs enabled --
        received: list[tuple[int, Message]] = []

        def on_message(sock: socket.socket, msg: Message) -> None:
            received.append((sock.fileno(), msg))

        unix_listener = SocketListener(
            SocketListenerCallbacks(
                on_message=on_message,
                on_client_disconnected=lambda _fd: None,
                on_error=lambda _sev, _msg, _ctx: None,
            )
        )
        ca = CertificateAuthority.create()
        cross_host = CrossHostListener(_server_ssl_context(ca, tmp_path))
        sock_path = Path(tempfile.mkdtemp(prefix="lux-")) / "d.sock"

        try:
            unix_listener.setup(sock_path)
            tcp_port = _free_port()
            cross_host.setup("127.0.0.1", tcp_port)

            # -- an ordinary same-host Hub, unaffected by cross-host being enabled --
            unix_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            unix_client.connect(str(sock_path))

            # -- a remote Hub, mTLS-authenticated --
            client_ctx = _client_ssl_context(ca, tmp_path)
            tls_thread, tls_result = _connect_tls_in_background(client_ctx, tcp_port)

            try:
                unix_listener.accept_connections()  # promotes the AF_UNIX peer
                unix_server_fd = unix_listener.clients[0].fileno()  # server's own fd
                _drive_until_tls_ready(unix_listener, cross_host)
                tls_thread.join(timeout=5.0)
                assert not tls_thread.is_alive()
                assert tls_result, "the TLS client never completed its handshake"
                tls_client = tls_result[0]

                # -- both legs, in one client set, both got ReadyMessage --
                assert len(unix_listener.clients) == 2
                assert isinstance(recv_message(unix_client, timeout=2.0), ReadyMessage)
                assert isinstance(recv_message(tls_client, timeout=2.0), ReadyMessage)

                # -- one poll_clients() cycle dispatches both legs' messages --
                unix_scene = SceneMessage(
                    id="unix-scene",
                    elements=[TextElement(id="t1", content="local")],
                    frame_id="unix-scene",
                )
                tls_scene = SceneMessage(
                    id="tls-scene",
                    elements=[TextElement(id="t2", content="remote")],
                    frame_id="tls-scene",
                )
                send_message(unix_client, unix_scene)
                send_message(tls_client, tls_scene)

                # select() needs a beat to see both sockets readable.
                unix_listener.poll_clients()
                deadline_rounds = 100
                while len(received) < 2 and deadline_rounds:
                    unix_listener.poll_clients()
                    deadline_rounds -= 1

                dispatched_ids = {
                    msg.id for _fd, msg in received if isinstance(msg, SceneMessage)
                }
                assert dispatched_ids == {"unix-scene", "tls-scene"}

                # -- closing the TLS leg leaves the AF_UNIX leg untouched --
                tls_client.close()
                for _ in range(50):
                    unix_listener.poll_clients()
                assert len(unix_listener.clients) == 1
                assert unix_server_fd in unix_listener.fd_to_client
            finally:
                unix_client.close()
                if tls_result:
                    tls_result[0].close()
        finally:
            unix_listener.shutdown()
            cross_host.shutdown()
