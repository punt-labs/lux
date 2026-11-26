"""Process creation boundary, separate from named-session ownership."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from punt_lux.pty.holder import PtyHolder

if TYPE_CHECKING:
    from punt_lux.pty.process_port import ProcessPort
    from punt_lux.wire.stream.new_request import NewRequest

type ProcessCreator = Callable[[NewRequest], ProcessPort]


class ProcessFactory:
    """Start the login shell; a request names a launcher, never a command line."""

    @staticmethod
    def start(request: NewRequest) -> ProcessPort:
        return PtyHolder(cols=request.cols, rows=request.rows)
