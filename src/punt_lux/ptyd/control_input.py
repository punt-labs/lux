"""Transport adapter for control frames, separate from session operations."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.control import ControlCodec
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.control_dispatch import ControlDispatch
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewers import ViewerBindings


class ControlInput:
    _dispatch: ControlDispatch

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._dispatch = ControlDispatch(core, bindings)
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if frame.kind is not FrameKind.DATA:
            raise ValueError("control channel accepts DATA only")
        request = ControlCodec.decode(frame.payload)
        try:
            self._dispatch.execute(peer, request)
        except (ValueError, RuntimeError, OSError) as error:
            StreamPublisher.failure(peer, request.request_id, str(error)[:4096])
