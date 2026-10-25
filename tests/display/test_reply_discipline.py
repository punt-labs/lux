"""The display answers every request once, in order, or ends the connection.

The Hub matches an ack, a pong and a query response to its request by position and
order, with no request id. That holds only if the display never drops a reply on a
connection it keeps: a reply it cannot send before its deadline ends the
connection, and the Hub redials. These tests pin that discipline for every reply
the render loop makes, for a Hub that reads (every request answered once, in order)
and for one that does not (the connection is severed, not skipped).
"""

from __future__ import annotations

import errno
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.display import RenderLoop
from punt_lux.protocol import (
    AckMessage,
    FrameReader,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    RemoteEventHandlerInvocation,
    SceneMessage,
    TextElement,
)
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY

if TYPE_CHECKING:
    import socket

    from punt_lux.protocol import Message

_FD = 4711


@final
class _Peer:
    """A client socket that takes every byte, or would block on every send."""

    sent: bytearray
    closed: bool
    _blocked: bool

    def __new__(cls, *, blocked: bool = False) -> Self:
        self = super().__new__(cls)
        self.sent = bytearray()
        self.closed = False
        self._blocked = blocked
        return self

    def send(self, data: memoryview) -> int:
        if self._blocked:
            raise BlockingIOError(errno.EAGAIN, "resource temporarily unavailable")
        self.sent.extend(bytes(data))
        return len(data)

    def block(self) -> None:
        """From now on every send would block: the Hub has stopped reading."""
        self._blocked = True

    def unblock(self) -> None:
        """The Hub reads again."""
        self._blocked = False

    def fileno(self) -> int:
        return _FD

    def close(self) -> None:
        self.closed = True

    def replies(self) -> list[Message]:
        """Everything the display wrote to this client, decoded in order."""
        reader = FrameReader()
        reader.feed(bytes(self.sent))
        return reader.drain_typed(DISPLAY_VOCABULARY)


def _hub_client(*, blocked: bool = False) -> tuple[RenderLoop, _Peer, socket.socket]:
    loop = RenderLoop("/tmp/test-lux-replies.sock")
    peer = _Peer(blocked=blocked)
    sock = cast("socket.socket", peer)
    listener = loop._socket_listener
    listener.clients.append(sock)
    listener.fd_to_client[_FD] = sock
    listener.register_client_identity(_FD, kind="hub", name="hub", connect_time=0.0)
    return loop, peer, sock


def _never_writable(
    _r: list[object], _w: list[object], _x: list[object], _t: float
) -> tuple[list[object], list[object], list[object]]:
    return ([], [], [])


def _scene(scene_id: str) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=scene_id,
    )


class TestAHubThatReads:
    def test_every_scene_is_acked_once_in_the_order_it_was_sent(self) -> None:
        loop, peer, sock = _hub_client()

        for scene_id in ("a", "b", "a", "c"):
            loop._handle_message(sock, _scene(scene_id))

        acked = [r.scene_id for r in peer.replies() if isinstance(r, AckMessage)]
        assert acked == ["a", "b", "a", "c"]

    def test_every_ping_is_answered_by_one_pong_echoing_its_ts(self) -> None:
        loop, peer, sock = _hub_client()

        loop._handle_message(sock, PingMessage(ts=1.5))
        loop._handle_message(sock, PingMessage(ts=2.5))

        pongs = [r.ts for r in peer.replies() if isinstance(r, PongMessage)]
        assert pongs == [1.5, 2.5]

    def test_every_query_is_answered_by_one_response(self) -> None:
        loop, peer, sock = _hub_client()

        loop._handle_message(sock, QueryRequest(method="list_scenes"))
        loop._handle_message(sock, QueryRequest(method="list_scenes"))

        responses = [r for r in peer.replies() if isinstance(r, QueryResponse)]
        assert len(responses) == 2

    def test_a_scene_from_a_client_that_is_not_a_hub_is_not_acked(self) -> None:
        # A Hub link is never rejected, so the ack-per-scene rule does not bend;
        # a client the display refuses gets no ack, and is not a Hub's connection.
        loop, peer, sock = _hub_client()
        loop._socket_listener.register_client_identity(
            _FD, kind="test", name="probe", connect_time=0.0
        )

        loop._handle_message(sock, _scene("refused"))

        assert [r for r in peer.replies() if isinstance(r, AckMessage)] == []


class TestAHubThatDoesNotRead:
    @pytest.fixture(autouse=True)
    def _full_buffer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "punt_lux.bounded_send.select", SimpleNamespace(select=_never_writable)
        )

    def test_an_ack_that_cannot_be_sent_severs_the_connection(self) -> None:
        loop, peer, sock = _hub_client(blocked=True)

        loop._handle_message(sock, _scene("a"))

        assert peer.closed
        assert sock not in loop._socket_listener.clients

    def test_a_pong_that_cannot_be_sent_severs_the_connection(self) -> None:
        loop, peer, sock = _hub_client(blocked=True)

        loop._handle_message(sock, PingMessage(ts=1.0))

        assert peer.closed
        assert sock not in loop._socket_listener.clients

    def test_a_query_response_that_cannot_be_sent_severs_the_connection(self) -> None:
        loop, peer, sock = _hub_client(blocked=True)

        loop._handle_message(sock, QueryRequest(method="list_scenes"))

        assert peer.closed
        assert sock not in loop._socket_listener.clients

    def test_n_scenes_into_a_full_buffer_never_leave_a_connection_with_a_gap(
        self,
    ) -> None:
        loop, peer, sock = _hub_client(blocked=True)

        for i in range(5):
            if sock in loop._socket_listener.clients:
                loop._handle_message(sock, _scene(f"s{i}"))

        # Either every ack arrived (none did: nothing was writable), or the
        # connection ended; a live connection with a missing ack is the defect.
        assert peer.replies() == []
        assert peer.closed


class TestADeferredEventIsNotAReply:
    def test_an_interaction_a_blocked_hub_cannot_take_is_held_for_retry_not_severed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, peer, sock = _hub_client()
        loop._handle_message(sock, _scene("owned"))
        peer.block()
        monkeypatch.setattr(
            "punt_lux.bounded_send.select", SimpleNamespace(select=_never_writable)
        )
        event = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="owned"
        )

        removed, dropped = loop._interaction_delivery.deliver([event])

        assert (removed, dropped) == ((), ())  # held in the buffer, retried next frame
        assert not peer.closed
        assert sock in loop._socket_listener.clients

        peer.unblock()
        removed, dropped = loop._interaction_delivery.deliver([event])

        assert (removed, dropped) == ((event,), ())  # sent: out of the buffer
        delivered = [
            r for r in peer.replies() if isinstance(r, RemoteEventHandlerInvocation)
        ]
        assert delivered == [event]  # exactly once

        removed, _ = loop._interaction_delivery.deliver([])
        assert [r for r in peer.replies() if r == event] == [event]
