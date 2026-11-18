"""Snapshot adoption, input ownership and resize ordering without a GL window."""

from __future__ import annotations

import struct

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.snapshot import encode_binary, snapshot_version, tracked_terminal


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
        session.receive(Frame(1, FrameKind.DATA, bytes([27]) + b"[5n"))
        assert sent == []
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
        session.resize(40, 8)
        assert session.view.term.size == (20, 4)
        announcement = Frame(1, FrameKind.RESIZE, struct.pack("<HH", 40, 8))
        assert sent == [announcement]
        session.receive(announcement)
        assert session.view.term.size == (40, 8)
    finally:
        session.close()


def test_view_close_never_queues_session_kill_or_input() -> None:
    data = encode_binary(tracked_terminal(20, 4))
    sent: list[Frame] = []
    session = RemoteSession("shell", "", sent.append)
    begin(session, data)
    session.receive(Frame(1, FrameKind.SNAPSHOT, data))
    session.close()
    session.close()
    assert sent == []
    assert session.phase is RemotePhase.CLOSED
