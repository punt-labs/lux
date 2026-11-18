"""Publish ordered session bytes and explicit exit/failure notices to viewers."""

from __future__ import annotations

import json
from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec, SuccessReply
from punt_lux.ptyd.bindings import Binding, ViewerBindings
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.fault import SessionFault
from punt_lux.ptyd.output import SessionSnapshot
from punt_lux.ptyd.peer import Peer


class StreamPublisher:
    _core: SessionCore
    _bindings: ViewerBindings

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        return self

    def pump(self) -> None:
        for event in self._core.pump():
            binding = self._bindings.session(event.session)
            if binding is None:
                continue
            try:
                if isinstance(event, SessionFault):
                    self._bindings.close_session(event.session, event.message)
                else:
                    self._bytes(binding, event.data)
                    session = self._core.get(event.session)
                    if session.ended:
                        self._exit(binding, session.describe()["exit_code"])
            except (BufferError, ConnectionError):
                self._bindings.detach(binding.peer)
                binding.peer.close()

    def detach(self, peer: Peer) -> None:
        self._bindings.detach(peer)

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
        reply = SuccessReply(request_id, metadata)
        binding.peer.queue(Frame(0, FrameKind.DATA, ReplyCodec.encode(reply)))
        for offset in range(0, len(snapshot.data), 64 * 1024):
            binding.peer.queue(
                Frame(
                    binding.channel,
                    FrameKind.SNAPSHOT,
                    snapshot.data[offset : offset + 64 * 1024],
                )
            )

    @staticmethod
    def _bytes(binding: Binding, data: bytes) -> None:
        for offset in range(0, len(data), 64 * 1024):
            binding.peer.queue(
                Frame(
                    binding.channel, FrameKind.DATA, data[offset : offset + 64 * 1024]
                )
            )

    def _exit(self, binding: Binding, code: object) -> None:
        self._bindings.remove_session(binding.session)
        payload = json.dumps({"reason": "exited", "exit_code": code}).encode()
        binding.peer.queue(Frame(binding.channel, FrameKind.CLOSE, payload))
