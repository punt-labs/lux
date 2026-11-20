"""A lagged viewer re-syncs from the visible screen when no binary cut exists.

A program parked inside a long unterminated escape sequence exhausts the
terminal's continuation tracking, so ``encode_binary`` raises. The publisher
then repaints the viewer from the visible screen instead of waiting for parser
ground state, which a continuously flooding program never reaches.
"""

from __future__ import annotations

import json
from typing import Self, cast

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.output import SessionSnapshot
from punt_lux.ptyd.snapshot import (
    SnapshotError,
    encode_binary,
    screen_rows,
    tracked_terminal,
)
from punt_lux.ptyd.snapshot_encoding import SnapshotEncoding
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewers import ViewerBindings
from punt_lux.terminal.ffi import Terminal, terminal_title
from tests.ptyd.test_session_core import FakeFactory

ESC = "\x1b"
CSI = ESC + "["
# Longer than the 64 KiB continuation limit, and never terminated.
EXHAUSTING_OSC = ESC + "]2;" + "x" * 70_000


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
        """Detaching never closes the daemon terminal."""


def _visible_round_trip(term: Terminal) -> Terminal:
    data = SnapshotEncoding.VT.serialize(term)
    cols, rows = term.size
    return SnapshotEncoding.VT.restore(data, cols, rows)


def test_exhausted_continuation_cannot_cut_a_binary_snapshot() -> None:
    term = tracked_terminal(20, 4)
    term.feed("hello" + EXHAUSTING_OSC)
    with pytest.raises(SnapshotError):
        encode_binary(term)


def test_visible_repaint_restores_the_screen_when_the_binary_cut_fails() -> None:
    src = tracked_terminal(20, 4)
    src.feed("hello\r\nworld" + CSI + "2;3H" + EXHAUSTING_OSC)
    restored = _visible_round_trip(src)
    assert screen_rows(restored) == screen_rows(src)
    assert restored.cursor == src.cursor


def test_visible_repaint_keeps_the_alternate_screen_without_the_binary_codec() -> None:
    """The alternate screen is where tmux lives; its primary grid is not carried."""
    src = tracked_terminal(20, 4)
    src.feed("primary text\r\n" + CSI + "?1049h" + CSI + "HALT SCREEN" + EXHAUSTING_OSC)
    assert src.get("active_screen", "uint8_t")
    with pytest.raises(SnapshotError):
        encode_binary(src)
    restored = _visible_round_trip(src)
    assert restored.get("active_screen", "uint8_t")
    assert screen_rows(restored) == screen_rows(src)


def test_visible_repaint_matches_the_complete_repaint_at_ground_state() -> None:
    src = tracked_terminal(20, 4)
    src.feed(ESC + "]2;a title" + ESC + "\\" + "plain " + CSI + "31mred")
    visible = _visible_round_trip(src)
    assert screen_rows(visible) == screen_rows(src)
    assert terminal_title(visible) == terminal_title(src) == "a title"


def test_vt_snapshot_metadata_round_trips() -> None:
    snapshot = SessionSnapshot("tmux", 7, 20, 4, "v", b"paint", SnapshotEncoding.VT)
    assert snapshot.to_dict()["format"] == "vt"
    assert SessionSnapshot.from_dict(snapshot.to_dict(), b"paint") == snapshot


def test_unknown_snapshot_format_is_rejected() -> None:
    metadata = SessionSnapshot("tmux", 0, 20, 4, "v", b"x").to_dict()
    metadata["format"] = "mystery"
    with pytest.raises(ValueError, match="format"):
        SessionSnapshot.from_dict(metadata, b"x")


def _attached_viewer(core: SessionCore) -> tuple[StreamPublisher, _RecordingPeer]:
    session = core.acquire(AttachRequest(1, "shell", cols=20, rows=4))
    peer = _RecordingPeer()
    bindings = ViewerBindings()
    binding = bindings.add(peer, "shell", 20, 4)  # type: ignore[arg-type]  # fake peer
    StreamPublisher.attach(binding, 1, session.capture(), session.describe())
    # The initial reply goes through the control channel, not the frame list.
    binding.flow.drain()
    return StreamPublisher(core, bindings), peer


def _replicate(frames: tuple[Frame, ...]) -> RemoteSession:
    sent: list[Frame] = []
    replica = RemoteSession("shell", "", sent.append)
    for frame in frames:
        replica.receive(frame)
    return replica


def test_lagged_viewer_in_an_exhausted_sequence_resyncs_via_the_visible_repaint() -> (
    None
):
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        publisher, peer = _attached_viewer(core)
        factory.created[0].output.extend(
            [b"hello", EXHAUSTING_OSC.encode(), b"y" * (5 * 1024 * 1024)]
        )
        for _ in range(3):
            publisher.pump()
        kinds = [frame.kind for frame in peer.frames]
        starts = [f for f in peer.frames if f.kind is FrameKind.SNAPSHOT_START]
        assert len(starts) == 1
        start = cast("dict[str, object]", json.loads(starts[0].payload))
        assert start["format"] == "vt"
        assert FrameKind.SNAPSHOT in kinds
        replica = _replicate(peer.frames[peer.frames.index(starts[0]) :])
        try:
            assert replica.phase is RemotePhase.READY
            assert replica.view.term.text().startswith("hello")
        finally:
            replica.close()
    finally:
        core.close()


def test_lagged_viewer_at_ground_state_still_gets_the_binary_snapshot() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        publisher, peer = _attached_viewer(core)
        factory.created[0].output.extend([b"hello", b"y" * (5 * 1024 * 1024)])
        for _ in range(2):
            publisher.pump()
        starts = [f for f in peer.frames if f.kind is FrameKind.SNAPSHOT_START]
        assert len(starts) == 1
        assert cast("dict[str, object]", json.loads(starts[0].payload))["format"] == (
            "binary"
        )
        replica = _replicate(peer.frames[peer.frames.index(starts[0]) :])
        try:
            assert replica.phase is RemotePhase.READY
            # The flood scrolled "hello" away; the replica shows the flood.
            assert replica.view.term.text().startswith("yyyy")
        finally:
            replica.close()
    finally:
        core.close()
