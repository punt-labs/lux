"""Notice that a session's program ended, once, and leave its screen readable."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.session_state import SessionState

if TYPE_CHECKING:
    from punt_lux.pty.process_port import ProcessPort
    from punt_lux.pty.session_lifecycle import SessionLifecycle

ENDED_NOTICE = b"\r\n\x1b[?2026l\x1b[2m[process exited]\x1b[0m"


class ProgramExit:
    """Move a session from running to exited when its process is gone."""

    _process: ProcessPort
    _lifecycle: SessionLifecycle

    def __new__(cls, process: ProcessPort, lifecycle: SessionLifecycle) -> Self:
        self = super().__new__(cls)
        self._process, self._lifecycle = process, lifecycle
        return self

    def notice(self) -> bytes:
        """Return the screen notice the moment the program is first seen gone."""
        if self._process.alive or self._lifecycle.state is not SessionState.RUNNING:
            return b""
        self._process.close()  # retain the screen, not an exhausted master FD
        self._lifecycle.state = SessionState.EXITED
        return ENDED_NOTICE
