"""The session parser depends on process IO, not a concrete PTY implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProcessPort(Protocol):
    """A held process; closing a viewer must never close this object."""

    @property
    def alive(self) -> bool: ...

    @property
    def pid(self) -> int: ...

    @property
    def exit_code(self) -> int | None: ...

    def pump(self) -> bytes: ...

    def write(self, data: bytes) -> None: ...

    def resize(self, cols: int, rows: int) -> None: ...

    def close(self) -> None: ...
