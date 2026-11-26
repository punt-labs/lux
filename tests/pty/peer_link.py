"""A real ``Peer`` on a socketpair, with the far end decoded into frames."""

from __future__ import annotations

import socket
from typing import Self

from punt_lux.pty.dispatch import SessionDispatch
from punt_lux.pty.peer import Peer
from punt_lux.wire.stream.control import ControlCodec, ControlRequest
from punt_lux.wire.stream.frames import MAX_READ_BYTES, Frame, FrameDecoder, FrameKind
from punt_lux.wire.stream.replies import Reply, ReplyCodec
from punt_lux.wire.stream.session_events import SessionEvent


class PeerLink:
    """What a daemon connection looks like from the client's side."""

    _peer: Peer
    _far: socket.socket
    _decoder: FrameDecoder

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        near, self._far = socket.socketpair()
        self._far.setblocking(False)
        self._peer = Peer(near)
        self._peer.mark_ready()
        self._decoder = FrameDecoder()
        return self

    @property
    def peer(self) -> Peer:
        return self._peer

    def received(self) -> list[Frame]:
        """Flush what the daemon queued and return the frames that arrived."""
        if not self._peer.closed:
            self._peer.flush()
        frames: list[Frame] = []
        while True:
            try:
                data = self._far.recv(MAX_READ_BYTES)
            except BlockingIOError:
                return frames
            if not data:
                return frames
            frames.extend(self._decoder.feed(data))

    def close(self) -> None:
        self._peer.close()
        self._far.close()

    def request(self, dispatch: SessionDispatch, request: ControlRequest) -> Reply:
        """Send one control request through ``dispatch`` and return its reply."""
        frame = Frame(0, FrameKind.DATA, ControlCodec.encode(request))
        dispatch.receive(self._peer, frame)
        dispatch.pump()
        replies = [
            ReplyCodec.decode(f.payload)
            for f in self.received()
            if f.channel == 0 and b'"event"' not in f.payload
        ]
        assert len(replies) == 1, replies
        return replies[0]

    def settled(self, dispatch: SessionDispatch) -> list[Frame]:
        """Pump and flush until the daemon has nothing more for this peer."""
        frames: list[Frame] = []
        for _ in range(4):
            frames.extend(self.received())
            dispatch.pump()
        frames.extend(self.received())
        return frames

    @staticmethod
    def events(frames: list[Frame]) -> list[SessionEvent]:
        """The session events among ``frames``, in arrival order."""
        return [
            SessionEvent.decode(f.payload)
            for f in frames
            if f.channel == 0 and b'"event"' in f.payload
        ]
