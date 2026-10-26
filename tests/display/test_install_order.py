"""An earlier dial's scene is never installed after a later dial's (obligation O7).

The Hub clears the suspects an earlier dial left behind when it reads an ack on a
later one, which is sound only if the display has installed every scene of the earlier
dial before any of the later's. Two things give that order: the new dial's
``ConnectMessage`` precedes its scenes on its own stream, and handling it closes the
predecessor that declared the same ``HubId`` (DES-068), discarding every byte the
predecessor had not yet delivered; and a scene from a socket that has not identified
is refused and never acked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display import RenderLoop
from punt_lux.protocol import ConnectMessage, SceneMessage, TextElement

if TYPE_CHECKING:
    import socket


def _sock(fd: int) -> MagicMock:
    sock = MagicMock()
    sock.send.side_effect = len
    sock.fileno.return_value = fd
    return sock


def _scene(scene_id: str) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=scene_id,
    )


def _hub(loop: RenderLoop, sock: socket.socket, fd: int) -> None:
    loop._socket_listener.clients.append(sock)
    loop._socket_listener.fd_to_client[fd] = sock


_SAME_HUB = "pembroke\x1f123"


class TestAPredecessorIsClosedBeforeTheNewDialsFirstScene:
    def test_nothing_from_the_predecessor_is_installed_after_the_new_dial_identifies(
        self,
    ) -> None:
        loop = RenderLoop("/tmp/test-lux-install-order.sock")
        old, new = _sock(10), _sock(20)
        _hub(loop, old, 10)
        loop._handle_message(
            old, ConnectMessage(name="lux-mcp", kind="hub", hub_id=_SAME_HUB)
        )
        loop._handle_message(old, _scene("before"))
        _hub(loop, new, 20)

        loop._handle_message(
            new, ConnectMessage(name="lux-mcp", kind="hub", hub_id=_SAME_HUB)
        )
        loop._handle_message(old, _scene("late"))  # a byte the predecessor still held
        loop._handle_message(new, _scene("after"))

        assert loop._scenes.resolve_scene("before") is not None
        assert loop._scenes.resolve_scene("late") is None
        assert loop._scenes.resolve_scene("after") is not None

    def test_the_predecessor_is_gone_before_the_new_dial_installs_anything(
        self,
    ) -> None:
        loop = RenderLoop("/tmp/test-lux-install-order.sock")
        old, new = _sock(10), _sock(20)
        _hub(loop, old, 10)
        loop._handle_message(
            old, ConnectMessage(name="lux-mcp", kind="hub", hub_id=_SAME_HUB)
        )
        _hub(loop, new, 20)

        loop._handle_message(
            new, ConnectMessage(name="lux-mcp", kind="hub", hub_id=_SAME_HUB)
        )

        assert old not in loop._socket_listener.clients
        old.close.assert_called()


class TestAnUnidentifiedSocketsSceneIsRefusedAndNeverAcked:
    def test_no_ack_is_held_for_it(self) -> None:
        loop = RenderLoop("/tmp/test-lux-install-order.sock")
        stranger = _sock(10)
        _hub(loop, stranger, 10)

        loop._handle_message(stranger, _scene("s1"))
        loop._on_after_swap()

        assert loop._scenes.resolve_scene("s1") is None
        stranger.send.assert_not_called()
