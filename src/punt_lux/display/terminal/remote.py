# pyright: reportMissingModuleSource=false
"""One Display replica of a daemon-owned session; closing it never sends kill."""

from __future__ import annotations

import json
import struct
from collections.abc import Callable
from typing import Self, cast

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.view import TerminalView
from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control_fields import ControlFields
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.output import SessionSnapshot
from punt_lux.ptyd.snapshot import restore_binary, snapshot_version


class RemoteSession:
    _name: str
    _command: str
    _view: TerminalView
    _send: Callable[[Frame], None]
    _phase: RemotePhase
    _status: str
    _channel: int
    _size: int
    _metadata: dict[str, object]
    _snapshot: bytearray
    _bytes_in: int

    def __new__(cls, name: str, command: str, send: Callable[[Frame], None]) -> Self:
        AttachRequest(1, name, command)  # apply the daemon's public boundary locally
        self = super().__new__(cls)
        self._name, self._command, self._send = name, command, send
        self._view = TerminalView()
        self._view.on_input = self.write
        self._view.on_resize = self.resize
        self._phase = RemotePhase.CONNECTING
        self._status = "connecting to luxd-pty"
        self._channel = self._size = self._bytes_in = 0
        self._metadata = {}
        self._snapshot = bytearray()
        return self

    @property
    def name(self) -> str:
        return self._name

    @property
    def view(self) -> TerminalView:
        return self._view

    @property
    def bytes_in(self) -> int:
        return self._bytes_in

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def phase(self) -> RemotePhase:
        return self._phase

    def request(self, request_id: int) -> AttachRequest:
        cols, rows = self._view.size
        return AttachRequest(request_id, self._name, self._command, cols, rows)

    def begin(self, metadata: dict[str, object]) -> None:
        fields = ControlFields(metadata)
        if (
            fields.session() != self._name
            or fields.text("snapshot_version") != snapshot_version()
        ):
            raise ValueError("snapshot identity/version mismatch")
        self._channel = fields.integer("channel", 1, (1 << 32) - 1)
        self._size = fields.integer("size", 1, 16 * 1024 * 1024)
        self._metadata = metadata
        self._snapshot.clear()
        self._phase = RemotePhase.SNAPSHOT

    def receive(self, frame: Frame) -> None:
        if frame.kind is FrameKind.SNAPSHOT:
            self._collect(frame.payload)
        elif frame.kind is FrameKind.DATA:
            if self._phase is not RemotePhase.READY:
                raise ValueError("live bytes preceded snapshot completion")
            self._view.feed(frame.payload)
            self._bytes_in += len(frame.payload)
        elif frame.kind is FrameKind.RESIZE:
            self._size_changed(frame.payload)
        elif frame.kind is FrameKind.CLOSE:
            notice: object = json.loads(frame.payload.decode())
            if not isinstance(notice, dict):
                raise ValueError("invalid terminal close notice")
            reason = ControlFields(cast("dict[str, object]", notice)).text("reason")
            self._phase = (
                RemotePhase.EXITED if reason == "exited" else RemotePhase.FAILED
            )
            self._status = reason

    def write(self, data: bytes) -> None:
        if self._phase is RemotePhase.READY:
            for offset in range(0, len(data), 64 * 1024):
                self._send(
                    Frame(
                        self._channel, FrameKind.DATA, data[offset : offset + 64 * 1024]
                    )
                )

    def resize(self, cols: int, rows: int) -> None:
        if self._phase is RemotePhase.READY:
            AttachRequest(1, self._name, cols=cols, rows=rows)
            self._send(
                Frame(self._channel, FrameKind.RESIZE, struct.pack("<HH", cols, rows))
            )

    def disconnected(self, message: str) -> None:
        self._phase = RemotePhase.DISCONNECTED
        self._status = message
        self._channel = 0
        self._snapshot.clear()

    def fail(self, message: str) -> None:
        self._phase = RemotePhase.FAILED
        self._status = message

    def close(self) -> None:
        self._phase = RemotePhase.CLOSED
        self._view.close()
        self._snapshot.clear()

    def render_in_child(self, label: str, size: ImVec2) -> None:
        if self._phase in (RemotePhase.READY, RemotePhase.EXITED):
            self._view.render_in_child(label, size)
        else:
            imgui.text_unformatted(f"Terminal {self._name}: {self._status}")

    def _collect(self, data: bytes) -> None:
        if (
            self._phase is not RemotePhase.SNAPSHOT
            or len(self._snapshot) + len(data) > self._size
        ):
            raise ValueError("unexpected or oversized snapshot fragment")
        self._snapshot.extend(data)
        if len(self._snapshot) == self._size:
            checkpoint = SessionSnapshot.from_dict(
                self._metadata, bytes(self._snapshot)
            )
            self._view.adopt(restore_binary(checkpoint.data))
            self._snapshot.clear()
            self._phase = (
                RemotePhase.EXITED
                if self._metadata.get("ended") is True
                else RemotePhase.READY
            )
            if self._phase is RemotePhase.EXITED:
                self._send(Frame(self._channel, FrameKind.CLOSE, b""))

    def _size_changed(self, data: bytes) -> None:
        if len(data) != 4:
            raise ValueError("invalid grid announcement")
        cols, rows = struct.unpack("<HH", data)
        AttachRequest(1, self._name, cols=cols, rows=rows)
        self._view.resize_from_daemon(cols, rows)
