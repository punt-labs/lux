"""Translate operation faults to bounded replies, not daemon-wide shutdown."""

from __future__ import annotations

from punt_lux.pty.control_dispatch import ControlDispatch
from punt_lux.pty.operation_failure import OperationFailure
from punt_lux.pty.peer import Peer
from punt_lux.wire.stream.control import Request


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
            OperationFailure.send(peer, request.request_id, error)
