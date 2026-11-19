"""Clean up an isolated proof's owned processes on exit and timeout signals."""

from __future__ import annotations

import signal
from collections.abc import Callable
from types import FrameType, TracebackType
from typing import Self


class ProofSignals:
    _cleanup: Callable[[], None]
    _closed: bool
    _previous: dict[signal.Signals, Callable[[int, FrameType | None], object] | int | None]

    def __new__(cls, cleanup: Callable[[], None]) -> Self:
        self = super().__new__(cls)
        self._cleanup = cleanup
        self._closed = False
        self._previous = {}
        return self

    def __enter__(self) -> Self:
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._previous[sig] = signal.signal(sig, self._interrupt)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        finally:
            for sig, handler in self._previous.items():
                signal.signal(sig, handler)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._cleanup()

    def _interrupt(self, signum: int, frame: FrameType | None) -> None:
        if not self._closed:
            self.close()
            raise SystemExit(128 + signum)
