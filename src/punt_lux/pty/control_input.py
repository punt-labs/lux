"""Transport adapter for control frames, separate from session operations."""

from __future__ import annotations

from typing import Self

from punt_lux.pty.control_dispatch import ControlDispatch
from punt_lux.pty.control_failures import ControlFailures
from punt_lux.pty.core import SessionCore
from punt_lux.pty.peer import Peer
from punt_lux.pty.viewers import ViewerBindings
from punt_lux.wire.stream.control import ControlCodec
from punt_lux.wire.stream.frames import Frame, FrameKind


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
        ControlFailures.execute(self._dispatch, peer, request)
