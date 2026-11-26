"""A deterministic process port and factory; no shell, socket or window starts."""

from __future__ import annotations

from dataclasses import dataclass, field

from punt_lux.pty.process_port import ProcessPort
from punt_lux.wire.stream.new_request import NewRequest


@dataclass
class FakeProcess:
    """Deterministic IO port; no real shell, socket or window is started."""

    alive: bool = True
    pid: int = 123
    exit_code: int | None = None
    output: list[bytes] = field(default_factory=list)
    written: list[bytes] = field(default_factory=list)
    sizes: list[tuple[int, int]] = field(default_factory=list)
    close_calls: int = 0
    refuse_close: bool = False
    refuse_write: bool = False
    reaped: bool = True

    def pump(self) -> bytes:
        return self.output.pop(0) if self.output else b""

    def write(self, data: bytes) -> None:
        if self.refuse_write:
            raise BufferError("input full")
        self.written.append(data)

    def resize(self, cols: int, rows: int) -> None:
        self.sizes.append((cols, rows))

    def close(self) -> bool:
        if self.alive:
            self.close_calls += 1
        if self.refuse_close:
            raise OSError("close failed")
        self.alive = False
        return self.reaped


class FakeFactory:
    """Records every process it starts, in order."""

    def __init__(self) -> None:
        self.created: list[FakeProcess] = []
        self.requests: list[NewRequest] = []

    def __call__(self, request: NewRequest) -> ProcessPort:
        process = FakeProcess()
        self.created.append(process)
        self.requests.append(request)
        return process
