"""Credit-aware multicast output; stalled viewers do not block program reads."""

from __future__ import annotations

import logging
from typing import Self

from punt_lux.pty.core import SessionCore
from punt_lux.pty.fault import SessionFault
from punt_lux.pty.peer import Peer
from punt_lux.pty.snapshot_cut import SnapshotCut
from punt_lux.pty.viewers import Binding, ViewerBindings
from punt_lux.terminal.output import OutputChunk, SessionSnapshot
from punt_lux.terminal.snapshot import SnapshotError
from punt_lux.wire.stream.frames import Frame, FrameKind
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply

logger = logging.getLogger(__name__)


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
        if self._core.get(name).resize(cols, rows):
            for binding in self._bindings.session(name):
                binding.flow.request_repaint()

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
                StreamPublisher._repaint(binding, self._core)
            for frame in binding.flow.drain():
                binding.peer.queue(frame)
        except (BufferError, ConnectionError):
            self.detach(binding.peer)
            binding.peer.close()

    @staticmethod
    def _repaint(binding: Binding, core: SessionCore) -> None:
        """Resync one viewer; its failure never reaches the daemon loop."""
        try:
            session = core.get(binding.session)
            binding.flow.prepare(SnapshotCut(session).cut(), session.describe())
        except SnapshotError as error:
            # Not even the visible screen can be cut. Retry a few pumps, then
            # close this viewer so its client is not left on a frozen screen.
            if binding.repaints.record(
                binding.session, error, binding.flow.size.actual
            ):
                binding.flow.finish(f"terminal repaint failed: {error}")
        except RuntimeError as error:
            # Session closed, failed or removed: only this viewer is finished.
            logger.warning("terminal %s: repaint abandoned: %s", binding.session, error)
            binding.flow.finish(str(error))
        else:
            binding.repaints.clear()

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
