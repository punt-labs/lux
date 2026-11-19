"""Operation failures distinguish invalid requests from retryable resource faults."""

from __future__ import annotations

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec
from punt_lux.ptyd.peer import Peer


class OperationFailure:
    @staticmethod
    def send(peer: Peer, request_id: int, error: Exception) -> None:
        message = str(error)[:4096] or type(error).__name__
        reply = FailureReply(
            request_id, message, retryable=not isinstance(error, ValueError)
        )
        peer.queue(Frame(0, FrameKind.DATA, ReplyCodec.encode(reply)))
