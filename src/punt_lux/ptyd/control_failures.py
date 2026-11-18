"""Translate operation faults to bounded replies, not daemon-wide shutdown."""

from __future__ import annotations

from punt_lux.protocol.pty.control import Request
from punt_lux.ptyd.control_dispatch import ControlDispatch
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.stream_output import StreamPublisher


class ControlFailures:
    @staticmethod
    def execute(dispatch: ControlDispatch, peer: Peer, request: Request) -> None:
        try:
            dispatch.execute(peer, request)
        except (
            ValueError,
            RuntimeError,
            OSError,
            MemoryError,
            ExceptionGroup,
        ) as error:
            # ExceptionGroup contains ordinary failures only. A group containing
            # KeyboardInterrupt/SystemExit is BaseExceptionGroup and propagates.
            message = str(error)[:4096] or type(error).__name__
            StreamPublisher.failure(peer, request.request_id, message)
