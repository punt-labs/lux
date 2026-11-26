"""Coordinate control/stream handlers and publish ordered session output."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.control_dispatch import ControlDispatch
from punt_lux.pty.control_input import ControlInput
from punt_lux.pty.session_attach import SessionAttach
from punt_lux.pty.session_roster import SessionRoster
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.pty.viewer_input import StreamDispatch
from punt_lux.pty.viewers import ViewerBindings

if TYPE_CHECKING:
    from punt_lux.pty.core import SessionCore
    from punt_lux.pty.peer import Peer
    from punt_lux.wire.stream.frames import Frame


class SessionDispatch:
    """Bridge authenticated peer channels to the authoritative core."""

    _control: ControlInput
    _stream: StreamDispatch
    _publisher: StreamPublisher
    _roster: SessionRoster

    def __new__(cls, core: SessionCore) -> Self:
        self = super().__new__(cls)
        bindings = ViewerBindings()
        self._roster = SessionRoster(core, bindings)
        self._control = ControlInput(
            ControlDispatch(self._roster, SessionAttach(core, bindings))
        )
        self._publisher = StreamPublisher(core, bindings)
        self._stream = StreamDispatch(core, bindings, self._publisher)
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if frame.channel == 0:
            self._control.receive(peer, frame)
        else:
            self._stream.receive(peer, frame)

    def detach(self, peer: Peer) -> None:
        self._roster.detach(peer)
        self._publisher.detach(peer)

    def pump(self) -> None:
        """Publish output, end finished sessions, then deliver session events."""
        self._publisher.pump()
        self._roster.sweep()
