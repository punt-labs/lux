"""Authoritative terminal state owned by a process, never by a viewer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.program_exit import ProgramExit
from punt_lux.pty.session_lifecycle import SessionLifecycle
from punt_lux.pty.session_state import SessionState
from punt_lux.terminal.ffi_terminal import TerminalIO
from punt_lux.terminal.output import OutputChunk, SessionSnapshot
from punt_lux.terminal.snapshot import snapshot_version, tracked_terminal
from punt_lux.terminal.snapshot_encoding import SnapshotEncoding

if TYPE_CHECKING:
    from punt_lux.pty.process_port import ProcessPort
    from punt_lux.pty.session_spec import SessionSpec


class TerminalSession:
    """One held program plus Ghostty state and an output byte position."""

    _spec: SessionSpec
    _process: ProcessPort
    _term: TerminalIO
    _position: int
    _lifecycle: SessionLifecycle
    _exit: ProgramExit

    def __new__(cls, spec: SessionSpec, process: ProcessPort) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._process = process
        self._term = TerminalIO(tracked_terminal(spec.cols, spec.rows))
        # Only the authority answers program queries, never Display replicas.
        self._term.on_reply(process.write)
        self._position = 0
        self._lifecycle = SessionLifecycle(spec.name, process)
        self._exit = ProgramExit(process, self._lifecycle)
        return self

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def label(self) -> str:
        return self._spec.label

    @property
    def position(self) -> int:
        return self._position

    @property
    def ended(self) -> bool:
        return self._lifecycle.state is SessionState.EXITED

    @property
    def running(self) -> bool:
        return self._lifecycle.state is SessionState.RUNNING

    @property
    def finished(self) -> bool:
        """Whether the program ended or its IO failed: nothing more will be output."""
        return self._lifecycle.state in (SessionState.EXITED, SessionState.FAILED)

    def pump(self) -> OutputChunk:
        """Keep parsing while no viewer is attached; output remains sequenced."""
        start = self._position
        self._lifecycle.pump()
        if self._lifecycle.state in (SessionState.CLOSED, SessionState.FAILED):
            return OutputChunk(self.name, start, b"")
        self._check_usable()
        with self._lifecycle:
            data = self._process.pump() + self._exit.notice()
            if data:
                self._term.feed(data)
                self._position += len(data)
        return OutputChunk(self.name, start, data)

    def capture(
        self, encoding: SnapshotEncoding = SnapshotEncoding.BINARY
    ) -> SessionSnapshot:
        """Capture bytes and the cut atomically in this single-threaded core.

        BINARY raises ``SnapshotError`` mid-sequence once continuation tracking
        is exhausted. VT repaints the visible screen and works in any parser
        state, but raises ``SnapshotError`` if the formatted screen exceeds the
        snapshot size limit.

        Raises:
            RuntimeError: The session is closed or failed.
            SnapshotError: The cut cannot be made in this encoding.
        """
        self._check_usable()
        data = encoding.serialize(self._term.native)
        cols, rows = self._term.size
        return SessionSnapshot(
            self.name, self._position, cols, rows, snapshot_version(), data, encoding
        )

    def write(self, data: bytes) -> None:
        self._check_usable()
        if self._lifecycle.state is SessionState.RUNNING:
            self._process.write(data)

    def resize(self, cols: int, rows: int) -> bool:
        """Resize to ``cols`` x ``rows``; return whether the size changed."""
        self._check_usable()
        if self._term.size == (cols, rows):
            return False
        with self._lifecycle:
            self._process.resize(cols, rows)
            self._term.resize(cols, rows)
        return True

    def describe(self) -> dict[str, object]:
        return {
            **self._spec.identity(),
            "pid": self._process.pid,
            "position": self._position,
            "ended": self.ended,
            "state": self._lifecycle.state.value,
            "exit_code": self._process.exit_code,
        }

    def close(self) -> ProcessPort:
        """Close resources on explicit termination or daemon shutdown."""
        self._process.close()
        self._term.close()
        self._lifecycle.state = SessionState.CLOSED
        return self._process

    def _check_usable(self) -> None:
        if self._lifecycle.state in (SessionState.CLOSED, SessionState.FAILED):
            raise RuntimeError(f"terminal session is {self._lifecycle.state.value}")
