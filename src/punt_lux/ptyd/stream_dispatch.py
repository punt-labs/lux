"""Input, resize and detach on an already bound viewer channel."""

from __future__ import annotations

import struct
from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.bindings import ViewerBindings
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer


class StreamDispatch:
    """A CLOSE releases a viewer binding, never the underlying program."""

    _core: SessionCore
    _bindings: ViewerBindings

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if not peer.ready:
            raise ValueError("hello required")
        binding = self._bindings.channel(peer, frame.channel)
        if frame.kind is FrameKind.DATA:
            self._core.get(binding.session).write(frame.payload)
        elif frame.kind is FrameKind.RESIZE:
            if len(frame.payload) != 4:
                raise ValueError("resize needs cols/rows uint16")
            cols, rows = struct.unpack("<HH", frame.payload)
            self._core.resize(binding.session, cols, rows)
            peer.queue(Frame(frame.channel, FrameKind.RESIZE, frame.payload))
        elif frame.kind is FrameKind.CLOSE:
            self._bindings.remove_channel(peer, frame.channel)
        elif frame.kind is not FrameKind.CREDIT:
            raise ValueError("unsupported viewer stream frame")
