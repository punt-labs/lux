"""Viewer input and credit acknowledgments, independent of program lifetime."""

from __future__ import annotations

import struct
from typing import Self

from punt_lux.pty.core import SessionCore
from punt_lux.pty.peer import Peer
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.pty.viewers import ViewerBindings
from punt_lux.wire.stream.attach import AttachRequest
from punt_lux.wire.stream.frames import Frame, FrameKind


class StreamDispatch:
    _core: SessionCore
    _bindings: ViewerBindings
    _publisher: StreamPublisher

    def __new__(
        cls, core: SessionCore, bindings: ViewerBindings, publisher: StreamPublisher
    ) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings, self._publisher = core, bindings, publisher
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if not peer.ready:
            raise ValueError("hello required")
        binding = self._bindings.channel(peer, frame.channel)
        if frame.kind is FrameKind.DATA:
            cols, rows = binding.flow.size.wanted
            self._publisher.resize(binding.session, cols, rows)
            self._core.get(binding.session).write(frame.payload)
        elif frame.kind is FrameKind.RESIZE:
            if len(frame.payload) != 4:
                raise ValueError("resize needs cols/rows uint16")
            cols, rows = struct.unpack("<HH", frame.payload)
            AttachRequest(1, binding.session, cols=cols, rows=rows)
            binding.flow.size.want((cols, rows))
            self._publisher.resize(binding.session, cols, rows)
        elif frame.kind is FrameKind.CREDIT:
            if len(frame.payload) != 4:
                raise ValueError("credit needs a uint32 byte count")
            binding.flow.acknowledge(struct.unpack("<I", frame.payload)[0])
        elif frame.kind is FrameKind.CLOSE:
            self._bindings.remove_channel(peer, frame.channel)
        else:
            raise ValueError("unsupported viewer stream frame")
