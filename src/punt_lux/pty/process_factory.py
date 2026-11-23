"""Process creation boundary, separate from named-session ownership."""

from __future__ import annotations

import shlex
from collections.abc import Callable

from punt_lux.pty.holder import PtyHolder
from punt_lux.pty.process_port import ProcessPort
from punt_lux.wire.stream.attach import AttachRequest

__all__ = ["ProcessCreator", "ProcessFactory", "ProcessPort"]

type ProcessCreator = Callable[[AttachRequest], ProcessPort]


class ProcessFactory:
    """Execute an argv vector; never implicitly run a command through a shell."""

    @staticmethod
    def start(request: AttachRequest) -> ProcessPort:
        return PtyHolder(
            shlex.split(request.command), cols=request.cols, rows=request.rows
        )
