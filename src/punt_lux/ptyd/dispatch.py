"""Coordinate control/stream handlers and publish ordered session output."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.frames import Frame
from punt_lux.ptyd.control_input import ControlInput
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewer_input import StreamDispatch
from punt_lux.ptyd.viewers import ViewerBindings


class SessionDispatch:
    """Bridge authenticated peer channels to the authoritative core."""

    _control: ControlInput
    _stream: StreamDispatch
    _publisher: StreamPublisher

    def __new__(cls, core: SessionCore) -> Self:
        self = super().__new__(cls)
        bindings = ViewerBindings()
        self._control = ControlInput(core, bindings)
        self._publisher = StreamPublisher(core, bindings)
        self._stream = StreamDispatch(core, bindings, self._publisher)
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if frame.channel == 0:
            self._control.receive(peer, frame)
        else:
            self._stream.receive(peer, frame)

    def detach(self, peer: Peer) -> None:
        self._publisher.detach(peer)

    def pump(self) -> None:
        self._publisher.pump()
