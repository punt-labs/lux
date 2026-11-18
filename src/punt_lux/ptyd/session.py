"""Authoritative terminal state owned by a process, never by a viewer."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.output import OutputChunk, SessionSnapshot
from punt_lux.ptyd.process_port import ProcessPort
from punt_lux.ptyd.session_state import SessionState
from punt_lux.ptyd.snapshot import encode_binary, snapshot_version, tracked_terminal
from punt_lux.terminal.ffi_terminal import TerminalIO

_ENDED_NOTICE = b"\r\n\x1b[?2026l\x1b[2m[process exited]\x1b[0m"


class TerminalSession:
    """One held program plus Ghostty state and an output byte position."""

    _request: AttachRequest
    _process: ProcessPort
    _term: TerminalIO
    _position: int
    _state: SessionState

    def __new__(cls, request: AttachRequest, process: ProcessPort) -> Self:
        self = super().__new__(cls)
        self._request = request
        self._process = process
        self._term = TerminalIO(tracked_terminal(request.cols, request.rows))
        # Only the authoritative terminal answers program queries. A Display
        # replica must not forward a second copy of those automatic replies.
        self._term.on_reply(process.write)
        self._position = 0
        self._state = SessionState.RUNNING
        return self

    @property
    def name(self) -> str:
        return self._request.session

    @property
    def command(self) -> str:
        return self._request.command

    @property
    def position(self) -> int:
        return self._position

    @property
    def ended(self) -> bool:
        return self._state is SessionState.EXITED

    def pump(self) -> OutputChunk:
        """Keep parsing while no viewer is attached; output remains sequenced."""
        start = self._position
        if self._state in (SessionState.CLOSED, SessionState.FAILED):
            return OutputChunk(self.name, start, b"")
        self._check_usable()
        data = self._process.pump()
        if not self._process.alive and self._state is SessionState.RUNNING:
            self._state = SessionState.FAILED
            self._process.close()  # retain the screen, not an exhausted master FD
            self._state = SessionState.EXITED
            data += _ENDED_NOTICE
        if data:
            previous = self._state
            self._state = SessionState.FAILED
            self._term.feed(data)
            self._position += len(data)
            self._state = previous
        return OutputChunk(self.name, start, data)

    def capture(self) -> SessionSnapshot:
        """Capture bytes and the cut atomically in this single-threaded core."""
        self._check_usable()
        data = encode_binary(self._term.native)
        cols, rows = self._term.size
        return SessionSnapshot(
            self.name, self._position, cols, rows, snapshot_version(), data
        )

    def write(self, data: bytes) -> None:
        self._check_usable()
        if self._state is SessionState.RUNNING:
            self._process.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._check_usable()
        previous = self._state
        self._state = SessionState.FAILED
        self._process.resize(cols, rows)
        self._term.resize(cols, rows)
        self._state = previous

    def describe(self) -> dict[str, object]:
        return {
            "session": self.name,
            "command": self.command,
            "pid": self._process.pid,
            "position": self._position,
            "ended": self.ended,
            "state": self._state.value,
            "exit_code": self._process.exit_code,
        }

    def close(self) -> None:
        """Called only for explicit session termination or daemon shutdown."""
        self._process.close()
        self._term.close()
        self._state = SessionState.CLOSED

    def _check_usable(self) -> None:
        if self._state in (SessionState.CLOSED, SessionState.FAILED):
            raise RuntimeError(f"terminal session is {self._state.value}")
