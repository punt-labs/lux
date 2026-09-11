"""The content gate on a promoted cross-host TLS fd, through the real dispatch.

W13's threat-model suite deliberately stops at the TLS/verification layer and
notes the content gate on a promoted fd as "tested elsewhere." This is
elsewhere: a real mTLS peer is promoted onto the ordinary client set exactly as
the render loop's per-frame pump does it, then driven through the genuine
``SocketListener`` read/dispatch path -- no mock of the boundary. It guards the
``verify -> identify -> content`` order (Invariant 1) and the ``is_client``
short-circuit that drops a pipelined message after its connection was closed,
against a future refactor quietly regressing either.
"""

from __future__ import annotations

import ssl
import tempfile
from pathlib import Path

from punt_lux.display import RenderLoop
from punt_lux.domain.hub_id import HubId
from punt_lux.protocol import (
    ConnectMessage,
    SceneMessage,
    TextElement,
    encode_message,
    send_message,
)
from tests.display._mtls_harness import (
    BackgroundConnect,
    LoopbackListener,
    MtlsMaterial,
)


def _sock_path() -> str:
    return str(Path(tempfile.mkdtemp(prefix="lux-")) / "d.sock")


def _promoted_pair(
    tmp_path: Path,
) -> tuple[RenderLoop, LoopbackListener, BackgroundConnect, ssl.SSLSocket]:
    """Return (render loop, listener, background-connect, promoted server sock).

    Drives a real mTLS handshake through ``CrossHostListener`` (the peer cert
    SAN is ``hub1.example.com``), then promotes the verified server socket onto
    a windowless ``RenderLoop``'s client set -- the exact hand-off the per-frame
    pump makes.
    """
    material = MtlsMaterial(tmp_path)
    listener = LoopbackListener.serving(material.server_context())
    client = listener.connect(material.trusted_client_context("hub1.example.com"))
    outcome = listener.pump_until_settled()
    assert outcome.ready, "the trusted peer was never promoted past its handshake"
    server_sock = outcome.ready[0]
    client.join()
    loop = RenderLoop(_sock_path())
    loop.socket_listener.promote_connection(server_sock)
    return loop, listener, client, server_sock


def _drive_until_closed(loop: RenderLoop, server_sock: object, *, rounds: int) -> None:
    for _ in range(rounds):
        loop.socket_listener.poll_clients()
        if server_sock not in loop.socket_listener.clients:
            return


class TestPromotedContentGate:
    def test_a_scene_before_identify_is_rejected_and_closed(
        self, tmp_path: Path
    ) -> None:
        loop, listener, client, server_sock = _promoted_pair(tmp_path)
        try:
            # No ConnectMessage first -- an unidentified fd (kind_of is None).
            send_message(
                client.socket,
                SceneMessage(
                    id="s", elements=[TextElement(id="t", content="x")], frame_id="s"
                ),
            )
            _drive_until_closed(loop, server_sock, rounds=100)

            assert server_sock not in loop.socket_listener.clients  # closed
            assert loop.socket_listener.kind_of(server_sock.fileno()) is None
            assert not loop.scenes.frames  # content never installed
        finally:
            listener.shutdown()
            client.close()

    def test_a_bad_san_connect_then_scene_is_rejected_and_the_scene_dropped(
        self, tmp_path: Path
    ) -> None:
        loop, listener, client, server_sock = _promoted_pair(tmp_path)
        try:
            # Pipelined in one write: a Gate-2-failing connect (declared hostname
            # does not match the peer cert SAN hub1.example.com) followed by a
            # scene. The connect closes the fd; the scene must be dropped, not
            # processed against the just-closed connection (is_client guard).
            bad_hub = HubId("attacker.example.com", 123)
            connect = ConnectMessage(
                name="lux-mcp", kind="hub", hub_id=bad_hub.wire_token
            )
            scene = SceneMessage(
                id="s", elements=[TextElement(id="t", content="x")], frame_id="s"
            )
            client.socket.sendall(encode_message(connect) + encode_message(scene))
            _drive_until_closed(loop, server_sock, rounds=100)

            assert server_sock not in loop.socket_listener.clients  # closed at Gate 2
            assert loop.socket_listener.kind_of(server_sock.fileno()) is None
            assert loop.socket_listener.hub_fd_for(bad_hub) is None  # never registered
            assert not loop.scenes.frames  # the pipelined scene never landed
        finally:
            listener.shutdown()
            client.close()
