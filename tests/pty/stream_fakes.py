"""Fakes for driving ``StreamPublisher`` without sockets, PTYs or a terminal."""

from __future__ import annotations

from typing import Self

from punt_lux.pty.control_dispatch import ControlDispatch
from punt_lux.pty.control_input import ControlInput
from punt_lux.pty.core import SessionCore, SessionError
from punt_lux.pty.session_attach import SessionAttach
from punt_lux.pty.session_roster import SessionRoster
from punt_lux.pty.viewers import ViewerBindings
from punt_lux.terminal.output import OutputChunk, SessionSnapshot
from punt_lux.terminal.snapshot import ContinuationExhaustedError, SnapshotError
from punt_lux.terminal.snapshot_encoding import SnapshotEncoding
from punt_lux.wire.stream.frames import Frame

IDLE: dict[str, object] = {"ended": False, "exit_code": None}


class RecordingPeer:
    """Stands in for ``Peer`` where a test only needs the frames it was sent."""

    _frames: list[Frame]
    _closed: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = []
        self._closed = False
        return self

    @property
    def frames(self) -> tuple[Frame, ...]:
        return tuple(self._frames)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def ready(self) -> bool:
        return True

    def queue(self, frame: Frame) -> None:
        self._frames.append(frame)

    def close(self) -> None:
        self._closed = True


class MidSequenceSession:
    """A session whose checkpoint is perpetually mid-escape.

    By default the visible-screen repaint succeeds, as it does in the daemon
    once the binary cut fails. ``checkpoint_error`` makes the checkpoint raise
    instead: ``SnapshotError`` when not even the visible screen can be cut,
    ``RuntimeError`` when the session is closed or failed.
    """

    _name: str
    _pos: int
    _size: tuple[int, int]
    _checkpoint_error: Exception | None
    _checkpoint_calls: int

    def __new__(cls, name: str, *, checkpoint_error: Exception | None = None) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._pos = 0
        self._size = (80, 24)
        self._checkpoint_error = checkpoint_error
        self._checkpoint_calls = 0
        return self

    @property
    def checkpoint_calls(self) -> int:
        return self._checkpoint_calls

    @property
    def name(self) -> str:
        return self._name

    @property
    def ended(self) -> bool:
        return False

    def capture(
        self, encoding: SnapshotEncoding = SnapshotEncoding.BINARY
    ) -> SessionSnapshot:
        error = self._checkpoint_error
        if encoding is SnapshotEncoding.BINARY:
            if error is not None and not isinstance(error, SnapshotError):
                raise error
            raise ContinuationExhaustedError("mid-sequence")
        self._checkpoint_calls += 1
        if error is not None:
            raise error
        return SessionSnapshot(
            self._name, self._pos, 80, 24, "test", b"screen", SnapshotEncoding.VT
        )

    def describe(self) -> dict[str, object]:
        return dict(IDLE)

    def resize(self, cols: int, rows: int) -> bool:
        changed = self._size != (cols, rows)
        self._size = (cols, rows)
        return changed

    def emit(self, data: bytes) -> OutputChunk:
        chunk = OutputChunk(self._name, self._pos, data)
        self._pos += len(data)
        return chunk


class QueuedCore:
    """A core whose pump hands out exactly the chunks a test enqueued."""

    _sessions: dict[str, MidSequenceSession]
    _queued: list[OutputChunk]

    def __new__(cls, *sessions: MidSequenceSession) -> Self:
        self = super().__new__(cls)
        self._sessions = {session.name: session for session in sessions}
        self._queued = []
        return self

    def enqueue(self, name: str, data: bytes) -> None:
        self._queued.append(self._sessions[name].emit(data))

    def drop(self, name: str) -> None:
        """Remove a session whose output is still queued, as a kill would."""
        del self._sessions[name]

    def pump(self) -> list[OutputChunk]:
        drained, self._queued = self._queued, []
        return drained

    def get(self, name: str) -> MidSequenceSession:
        try:
            return self._sessions[name]
        except KeyError:
            raise SessionError(f"unknown terminal session {name}") from None

    def attach(self, name: str) -> MidSequenceSession:
        return self.get(name)

    def resize(self, name: str, cols: int, rows: int) -> bool:
        return self.get(name).resize(cols, rows)


class Controls:
    """Builds the control path over a core and bindings, as the daemon wires it."""

    @staticmethod
    def dispatch(core: SessionCore, bindings: ViewerBindings) -> ControlDispatch:
        roster = SessionRoster(core, bindings)
        return ControlDispatch(roster, SessionAttach(core, bindings))

    @staticmethod
    def input(core: SessionCore, bindings: ViewerBindings) -> ControlInput:
        return ControlInput(Controls.dispatch(core, bindings))
