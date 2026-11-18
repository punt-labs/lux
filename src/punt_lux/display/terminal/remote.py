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
from punt_lux.terminal.transfer import SnapshotTransfer


class RemoteSession:
    _name: str
    _command: str
    _view: TerminalView
    _send: Callable[[Frame], None]
    _phase: RemotePhase
    _status: str
    _channel: int
    _transfer: SnapshotTransfer
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
        self._channel = self._bytes_in = 0
        self._transfer = SnapshotTransfer(name)
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

    @property
    def status(self) -> str:
        return f"{self._phase.value}: {self._status}"

    def request(self, request_id: int) -> AttachRequest:
        cols, rows = self._view.size
        return AttachRequest(request_id, self._name, self._command, cols, rows)

    def begin(self, metadata: dict[str, object]) -> None:
        self._transfer.begin(metadata)
        self._channel = self._transfer.channel
        self._phase = RemotePhase.SNAPSHOT

    def receive(self, frame: Frame) -> None:
        if frame.kind is FrameKind.SNAPSHOT_START:
            self.begin(self._reset_metadata(frame.payload))
        elif frame.kind is FrameKind.SNAPSHOT:
            self._collect(frame.payload)
        elif frame.kind is FrameKind.DATA:
            if self._phase is not RemotePhase.READY:
                raise ValueError("live bytes preceded snapshot completion")
            self._view.feed(frame.payload)
            self._bytes_in += len(frame.payload)
            self._acknowledge(len(frame.payload))
        elif frame.kind is FrameKind.CLOSE:
            self._notice(frame.payload)

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
        self._transfer.clear()

    def fail(self, message: str) -> None:
        self._phase = RemotePhase.FAILED
        self._status = message

    def close(self) -> None:
        self._phase = RemotePhase.CLOSED
        self._view.close()
        self._transfer.clear()

    def render_in_child(self, label: str, size: ImVec2) -> None:
        if self._phase in (RemotePhase.READY, RemotePhase.EXITED):
            self._view.render_in_child(label, size)
        else:
            imgui.text_unformatted(f"Terminal {self._name}: {self.status}")

    def _collect(self, data: bytes) -> None:
        if self._phase is not RemotePhase.SNAPSHOT:
            raise ValueError("unexpected snapshot fragment")
        native = self._transfer.feed(data)
        self._acknowledge(len(data))
        if native is not None:
            self._view.adopt(native)
            self._phase = (
                RemotePhase.EXITED if self._transfer.ended else RemotePhase.READY
            )

    def _acknowledge(self, amount: int) -> None:
        if amount and self._phase in (
            RemotePhase.SNAPSHOT,
            RemotePhase.READY,
            RemotePhase.EXITED,
        ):
            self._send(
                Frame(self._channel, FrameKind.CREDIT, struct.pack("<I", amount))
            )

    def _notice(self, data: bytes) -> None:
        notice: object = json.loads(data.decode())
        if not isinstance(notice, dict):
            raise ValueError("invalid terminal close notice")
        reason = ControlFields(cast("dict[str, object]", notice)).text("reason")
        self._phase = RemotePhase.EXITED if reason == "exited" else RemotePhase.FAILED
        self._status = reason
        self._transfer.clear()
        self._send(Frame(self._channel, FrameKind.CLOSE, b""))

    @staticmethod
    def _reset_metadata(data: bytes) -> dict[str, object]:
        raw: object = json.loads(data.decode())
        if not isinstance(raw, dict):
            raise ValueError("invalid snapshot reset")
        return cast("dict[str, object]", raw)
