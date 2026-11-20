"""A viewer that fell behind must still repaint under continuous output.

tmux and other full-screen programs stream without ever pausing at parser
ground state. When such a viewer lags past its backlog limit the publisher
switches it to a repaint, but the repaint is a snapshot that can only be cut
when the terminal reaches ground state. If the publisher keeps deferring the
snapshot because the program is always mid-sequence, the viewer is starved: it
shows stale content for as long as the output keeps flowing. This test pins
that behaviour so a fix can prove it is gone.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.frames import Frame
from punt_lux.ptyd.output import OutputChunk, SessionSnapshot
from punt_lux.ptyd.snapshot import SnapshotError
from punt_lux.ptyd.snapshot_encoding import SnapshotEncoding
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewers import ViewerBindings


class _RecordingPeer:
    """A viewer connection that records queued frames instead of writing a socket."""

    _frames: list[Frame]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = []
        return self

    @property
    def frames(self) -> tuple[Frame, ...]:
        return tuple(self._frames)

    def queue(self, frame: Frame) -> None:
        self._frames.append(frame)

    def close(self) -> None:
        """A detach never closes the underlying terminal; nothing to do here."""


class _AlwaysMidSequence:
    """A session whose capture never succeeds: it is perpetually mid-escape."""

    _name: str
    _pos: int

    def __new__(cls, name: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._pos = 0
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
        return SessionSnapshot(
            self._name, self._pos, 80, 24, "test", b"screen", SnapshotEncoding.VT
        )

    def describe(self) -> dict[str, object]:
        return {"ended": False, "exit_code": None}

    def emit(self, data: bytes) -> OutputChunk:
        chunk = OutputChunk(self._name, self._pos, data)
        self._pos += len(data)
        return chunk


class _FakeCore:
    _session: _AlwaysMidSequence
    _queued: list[OutputChunk]

    def __new__(cls, session: _AlwaysMidSequence) -> Self:
        self = super().__new__(cls)
        self._session = session
        self._queued = []
        return self

    def enqueue(self, data: bytes) -> None:
        self._queued.append(self._session.emit(data))

    def pump(self) -> list[OutputChunk]:
        drained, self._queued = self._queued, []
        return drained

    def get(self, _name: str) -> _AlwaysMidSequence:
        return self._session


def test_lagged_viewer_is_not_starved_by_a_program_that_never_settles() -> None:
    """A viewer forced into repaint must eventually get frames even while the

    program stays mid-sequence every pump. Today the publisher defers the
    snapshot forever and the viewer receives nothing, so this fails until the
    starvation is fixed.
    """
    session = _AlwaysMidSequence("tmux")
    core = _FakeCore(session)
    peer = _RecordingPeer()
    bindings = ViewerBindings()
    binding = bindings.add(peer, "tmux", 80, 24)  # type: ignore[arg-type]  # fake peer
    binding.flow.prepare(
        SessionSnapshot("tmux", 0, 80, 24, "test", b""),
        {"ended": False, "exit_code": None},
        initial=True,
    )
    binding.flow.drain()
    peer_frames_before = len(peer.frames)

    publisher = StreamPublisher(core, bindings)  # type: ignore[arg-type]  # fake core

    # Overflow the backlog so the flow switches to repaint, then keep the
    # program flowing for many pumps, each still mid-sequence and far enough
    # apart in wall-clock for defer_repaint's retry window to elapse.
    core.enqueue(b"x" * (8 * 1024 * 1024))
    publisher.pump()
    assert binding.flow.wants_repaint or binding.flow.lag_bytes == 0  # repaint armed

    for _ in range(50):
        core.enqueue(b"\x1b[1")  # a perpetual partial CSI: capture() will raise
        publisher.pump()

    delivered = len(peer.frames) - peer_frames_before
    assert delivered > 0, "viewer received no frames while the program kept flowing"
