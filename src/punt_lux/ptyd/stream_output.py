"""Credit-aware multicast output; stalled viewers do not block program reads."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec, SuccessReply
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.fault import SessionFault
from punt_lux.ptyd.output import OutputChunk, SessionSnapshot
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.snapshot import SnapshotError
from punt_lux.ptyd.viewers import Binding, ViewerBindings


class StreamPublisher:
    _core: SessionCore
    _bindings: ViewerBindings

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        return self

    def pump(self) -> None:
        for event in self._core.pump():
            self._record(event)
        for binding in self._bindings.all:
            self._flush(binding)

    def detach(self, peer: Peer) -> None:
        self._bindings.detach(peer)

    def resize(self, name: str, cols: int, rows: int) -> None:
        viewers = self._bindings.session(name)
        if viewers and viewers[0].flow.actual_size == (cols, rows):
            return
        session = self._core.get(name)
        self._core.resize(name, cols, rows)
        snapshot = session.capture()
        for binding in self._bindings.session(name):
            binding.flow.prepare(snapshot, session.describe())

    def _record(self, event: OutputChunk | SessionFault) -> None:
        for binding in self._bindings.session(event.session):
            if isinstance(event, SessionFault):
                binding.flow.finish(event.message)
            else:
                binding.flow.append(event.data)
                session = self._core.get(event.session)
                if session.ended:
                    binding.flow.finish("exited", session.describe()["exit_code"])

    def _flush(self, binding: Binding) -> None:
        try:
            if binding.flow.wants_repaint:
                session = self._core.get(binding.session)
                binding.flow.prepare(session.capture(), session.describe())
            for frame in binding.flow.drain():
                binding.peer.queue(frame)
        except SnapshotError:
            # Continuation tracking can be exhausted mid-sequence. Leave only
            # this viewer waiting; the core keeps parsing until ground state.
            binding.flow.defer_repaint()
            return
        except (BufferError, ConnectionError):
            self.detach(binding.peer)
            binding.peer.close()

    @staticmethod
    def success(peer: Peer, request_id: int, result: dict[str, object]) -> None:
        peer.queue(
            Frame(
                0, FrameKind.DATA, ReplyCodec.encode(SuccessReply(request_id, result))
            )
        )

    @staticmethod
    def failure(peer: Peer, request_id: int, error: str) -> None:
        peer.queue(
            Frame(0, FrameKind.DATA, ReplyCodec.encode(FailureReply(request_id, error)))
        )

    @staticmethod
    def attach(
        binding: Binding,
        request_id: int,
        snapshot: SessionSnapshot,
        description: dict[str, object],
    ) -> None:
        metadata = snapshot.to_dict()
        metadata.update(
            channel=binding.channel,
            ended=description["ended"],
            exit_code=description["exit_code"],
        )
        StreamPublisher.success(binding.peer, request_id, metadata)
        binding.flow.prepare(snapshot, description, initial=True)
