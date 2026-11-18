"""Coordinate control/stream handlers and publish ordered session output."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.bindings import ViewerBindings
from punt_lux.ptyd.control_dispatch import ControlDispatch
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.fault import SessionFault
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.stream_dispatch import StreamDispatch


class SessionDispatch:
    """Bridge authenticated peer channels to the authoritative core."""

    _core: SessionCore
    _bindings: ViewerBindings
    _control: ControlDispatch
    _stream: StreamDispatch

    def __new__(cls, core: SessionCore) -> Self:
        self = super().__new__(cls)
        self._core = core
        self._bindings = ViewerBindings()
        self._control = ControlDispatch(core, self._bindings)
        self._stream = StreamDispatch(core, self._bindings)
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if frame.channel == 0:
            self._control.receive(peer, frame)
        else:
            self._stream.receive(peer, frame)

    def detach(self, peer: Peer) -> None:
        self._bindings.detach(peer)

    def pump(self) -> None:
        for event in self._core.pump():
            binding = self._bindings.session(event.session)
            if binding is None:
                continue
            try:
                if isinstance(event, SessionFault):
                    self._bindings.close_session(event.session, event.message)
                else:
                    for offset in range(0, len(event.data), 64 * 1024):
                        binding.peer.queue(
                            Frame(
                                binding.channel,
                                FrameKind.DATA,
                                event.data[offset : offset + 64 * 1024],
                            )
                        )

            except (BufferError, ConnectionError):
                self.detach(binding.peer)
                binding.peer.close()
