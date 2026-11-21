"""Fakes for driving ``StreamPublisher`` without sockets, PTYs or a terminal."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.frames import Frame
from punt_lux.ptyd.output import OutputChunk, SessionSnapshot
from punt_lux.ptyd.snapshot import SnapshotError
from punt_lux.ptyd.snapshot_encoding import SnapshotEncoding

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
    """A session that is perpetually mid-escape.

    ``binary_fails`` makes the binary cut raise, as it does once continuation
    tracking is exhausted. ``visible_fails`` also makes the visible repaint
    raise, as it does when the formatted screen exceeds the snapshot limit.
    """

    _name: str
    _pos: int
    _visible_fails: bool

    def __new__(cls, name: str, *, visible_fails: bool = False) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._pos = 0
        self._visible_fails = visible_fails
        return self

    @property
    def name(self) -> str:
        return self._name

    @property
    def ended(self) -> bool:
        return False

    def capture(
        self, encoding: SnapshotEncoding = SnapshotEncoding.BINARY
    ) -> SessionSnapshot:
        if encoding is SnapshotEncoding.BINARY:
            raise SnapshotError("continuation tracking exhausted mid-sequence")
        if self._visible_fails:
            raise SnapshotError("formatted screen exceeds the supported size")
        return SessionSnapshot(
            self._name, self._pos, 80, 24, "test", b"screen", SnapshotEncoding.VT
        )

    def describe(self) -> dict[str, object]:
        return dict(IDLE)

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

    def pump(self) -> list[OutputChunk]:
        drained, self._queued = self._queued, []
        return drained

    def get(self, name: str) -> MidSequenceSession:
        return self._sessions[name]

    def acquire(self, request: AttachRequest) -> MidSequenceSession:
        return self._sessions[request.session]

    def resize(self, _name: str, _cols: int, _rows: int) -> None:
        """The fake session has a fixed size."""
