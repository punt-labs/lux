"""An ack means a frame survived the scene: the display holds it until the swap.

The display installs a scene on receipt and sends its ack only after the next
completed buffer swap, every held ack in receipt order, whether or not the scene was
visible. A scene that crashes its install or the frame after it is therefore still
unacked when the dial ends, and the Hub can name it a suspect. An ack held for a
client that left before the swap is dropped.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from punt_lux.display import client_sender
from punt_lux.display.client_sender import ClientSender
from punt_lux.protocol import AckMessage, SceneMessage, TextElement
from tests.display.test_reply_discipline import _FD, _hub_client, _Peer

if TYPE_CHECKING:
    import socket

    import pytest

    from punt_lux.display import RenderLoop
    from punt_lux.display.client_host_port import ClientHost


def _scene(scene_id: str, frame_id: str | None = None) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=frame_id or scene_id,
    )


def _acked(peer: _Peer) -> list[str]:
    return [r.scene_id for r in peer.replies() if isinstance(r, AckMessage)]


def _swap(loop: RenderLoop) -> None:
    loop._on_after_swap()


class TestAnAckIsHeldUntilTheSwap:
    def test_installing_a_scene_sends_no_ack(self) -> None:
        loop, peer, sock = _hub_client()

        loop._handle_message(sock, _scene("a"))

        assert _acked(peer) == []

    def test_the_swap_sends_the_ack(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a"))

        _swap(loop)

        assert _acked(peer) == ["a"]

    def test_an_ack_is_sent_once_whatever_the_number_of_swaps(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a"))

        _swap(loop)
        _swap(loop)

        assert _acked(peer) == ["a"]

    def test_a_swap_with_nothing_held_sends_nothing(self) -> None:
        loop, peer, _sock = _hub_client()

        _swap(loop)

        assert _acked(peer) == []


class TestHeldAcksGoOutInReceiptOrder:
    def test_one_swap_flushes_every_held_ack_in_the_order_received(self) -> None:
        loop, peer, sock = _hub_client()
        for scene_id in ("a", "b", "a", "c"):
            loop._handle_message(sock, _scene(scene_id))

        _swap(loop)

        assert _acked(peer) == ["a", "b", "a", "c"]

    def test_a_scene_received_after_a_swap_waits_for_the_next(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a"))
        _swap(loop)
        loop._handle_message(sock, _scene("b"))

        assert _acked(peer) == ["a"]
        _swap(loop)

        assert _acked(peer) == ["a", "b"]


class TestAnAckDoesNotDependOnVisibility:
    def test_a_scene_in_a_docked_frame_is_acked_at_the_swap(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a", "f1"))
        loop._scenes.minimize("f1")

        _swap(loop)

        assert _acked(peer) == ["a"]

    def test_a_scene_in_a_closed_frame_is_acked_at_the_swap(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a", "f1"))
        loop._scenes.close("f1")

        _swap(loop)

        assert _acked(peer) == ["a"]


class TestAClientThatLeftBeforeTheSwap:
    def test_its_held_acks_are_dropped(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a"))
        loop._socket_listener.remove_client(sock)

        _swap(loop)

        assert _acked(peer) == []

    def test_another_clients_acks_still_go_out(self) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("a"))
        gone = cast("socket.socket", object())
        loop._sender.hold_ack(gone, "orphan")

        _swap(loop)

        assert _acked(peer) == ["a"]


class TestAScenePairedWithNoHubHoldsNoAck:
    def test_a_refused_scene_is_never_acked(self) -> None:
        loop, peer, sock = _hub_client()
        loop._socket_listener.register_client_identity(
            _FD, kind="test", name="probe", connect_time=0.0
        )

        loop._handle_message(sock, _scene("refused"))
        _swap(loop)

        assert _acked(peer) == []


def test_the_swap_logs_nothing_however_many_acks_it_flushes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    loop, _peer, sock = _hub_client()
    for scene_id in ("a", "b", "c"):
        loop._handle_message(sock, _scene(scene_id))

    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        _swap(loop)

    assert caplog.records == []


class _Host:
    """A client set that records who was severed."""

    clients: list[socket.socket]
    severed: list[socket.socket]

    def __init__(self, *clients: socket.socket) -> None:
        self.clients = list(clients)
        self.severed = []

    def is_client(self, sock: socket.socket) -> bool:
        return sock in self.clients

    def remove_client(self, sock: socket.socket) -> None:
        self.clients.remove(sock)
        self.severed.append(sock)


class TestTheHeldAcksShareOnePostSwapBudget:
    def test_two_stalled_clients_are_bounded_by_one_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        waits: list[float] = []

        def stalled(
            _r: list[object], _w: list[object], _x: list[object], timeout: float
        ) -> tuple[list[object], list[object], list[object]]:
            waits.append(timeout)
            time.sleep(timeout)  # a peer that never drains: the wait runs to its end
            return ([], [], [])

        monkeypatch.setattr(
            "punt_lux.bounded_send.select", SimpleNamespace(select=stalled)
        )
        monkeypatch.setattr(client_sender, "_SWAP_SEND_BUDGET", 0.05)
        monkeypatch.setattr(client_sender, "_ONE_OFF_SEND_BUDGET", 5.0)
        first = cast("socket.socket", _Peer(blocked=True))
        second = cast("socket.socket", _Peer(blocked=True))
        host = _Host(first, second)
        sender = ClientSender(cast("ClientHost", host))
        sender.hold_ack(first, "a")
        sender.hold_ack(second, "b")

        sender.release_acks()

        assert len(waits) == 1, "the second client waited on a budget of its own"
        assert waits[0] <= 0.05
        assert host.severed == [first, second]

    def test_the_deadline_is_cleared_once_the_acks_are_out(self) -> None:
        host = _Host()
        sender = ClientSender(cast("ClientHost", host))

        sender.release_acks()

        assert sender._frame_deadline is None
