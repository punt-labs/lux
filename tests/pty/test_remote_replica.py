"""Snapshot adoption, input ownership and resize ordering without a GL window."""

from __future__ import annotations

import json
import struct

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.terminal.output import SessionSnapshot
from punt_lux.terminal.snapshot import encode_binary, snapshot_version, tracked_terminal
from punt_lux.wire.stream.frames import Frame, FrameKind


def begin(session: RemoteSession, data: bytes, ended: bool = False) -> None:
    session.begin(
        {
            "session": session.name,
            "position": 0,
            "cols": 20,
            "rows": 4,
            "snapshot_version": snapshot_version(),
            "format": "binary",
            "size": len(data),
            "channel": 1,
            "ended": ended,
            "exit_code": None,
        }
    )


def test_snapshot_must_complete_before_live_bytes() -> None:
    source = tracked_terminal(20, 4)
    source.feed(b"snapshot text")
    data = encode_binary(source)
    sent: list[Frame] = []
    session = RemoteSession("shell", "", sent.append)
    try:
        begin(session, data)
        session.receive(Frame(1, FrameKind.SNAPSHOT, data[:10]))
        assert session.phase.value == RemotePhase.SNAPSHOT.value
        with pytest.raises(ValueError, match="preceded"):
            session.receive(Frame(1, FrameKind.DATA, b"too soon"))
        session.receive(Frame(1, FrameKind.SNAPSHOT, data[10:]))
        assert session.phase is RemotePhase.READY
        assert session.view.term.text() == "snapshot text"
        session.receive(Frame(1, FrameKind.DATA, b" tail"))
        assert session.view.term.text() == "snapshot text tail"
    finally:
        session.close()


def test_replica_never_sends_automatic_query_replies() -> None:
    data = encode_binary(tracked_terminal(20, 4))
    sent: list[Frame] = []
    session = RemoteSession("shell", "", sent.append)
    try:
        begin(session, data)
        session.receive(Frame(1, FrameKind.SNAPSHOT, data))
        sent.clear()
        session.receive(Frame(1, FrameKind.DATA, bytes([27]) + b"[5n"))
        assert all(frame.kind is FrameKind.CREDIT for frame in sent)
        sent.clear()
        session.view.input.paste("hello")
        assert sent == [Frame(1, FrameKind.DATA, b"hello")]
    finally:
        session.close()


def test_resize_waits_for_authoritative_announcement() -> None:
    data = encode_binary(tracked_terminal(20, 4))
    sent: list[Frame] = []
    session = RemoteSession("shell", "", sent.append)
    try:
        begin(session, data)
        session.receive(Frame(1, FrameKind.SNAPSHOT, data))
        sent.clear()
        session.resize(40, 8)
        assert session.view.term.size == (20, 4)
        announcement = Frame(1, FrameKind.RESIZE, struct.pack("<HH", 40, 8))
        assert sent == [announcement]
        data = encode_binary(tracked_terminal(40, 8))
        metadata = SessionSnapshot(
            "shell", 0, 40, 8, snapshot_version(), data
        ).to_dict()
        metadata["channel"] = 1
        session.receive(
            Frame(1, FrameKind.SNAPSHOT_START, json.dumps(metadata).encode())
        )
        assert session.view.term.size == (20, 4)
        session.receive(Frame(1, FrameKind.SNAPSHOT, data))
        assert session.view.term.size == (40, 8)
    finally:
        session.close()


def test_view_close_never_queues_session_kill_or_input() -> None:
    data = encode_binary(tracked_terminal(20, 4))
    sent: list[Frame] = []
    session = RemoteSession("shell", "", sent.append)
    begin(session, data)
    session.receive(Frame(1, FrameKind.SNAPSHOT, data))
    sent.clear()
    session.close()
    session.close()
    assert sent == []
    assert session.phase is RemotePhase.CLOSED


@pytest.mark.parametrize("kind", [FrameKind.CREDIT, FrameKind.RESIZE])
def test_unexpected_daemon_stream_direction_is_rejected(kind: FrameKind) -> None:
    sent: list[Frame] = []
    session = RemoteSession("shell", "", sent.append)
    try:
        with pytest.raises(ValueError, match="unsupported daemon stream"):
            session.receive(Frame(1, kind, b""))
        assert not sent
    finally:
        session.close()
