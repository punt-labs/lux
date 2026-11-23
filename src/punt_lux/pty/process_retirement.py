"""Retain closing processes until pump-driven reaping completes."""

from __future__ import annotations

import logging
import time
from typing import Self

from punt_lux.pty.process_port import ProcessPort

logger = logging.getLogger(__name__)


class ProcessRetirement:
    _processes: dict[str, ProcessPort]
    _errors: dict[str, Exception]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._processes = {}
        self._errors = {}
        return self

    def __len__(self) -> int:
        return len(self._processes)

    def contains(self, name: str) -> bool:
        return name in self._processes

    def add(self, name: str, process: ProcessPort) -> None:
        self._processes[name] = process

    def forget(self, name: str) -> None:
        del self._processes[name]
        self._errors.pop(name, None)

    def stop(self, name: str) -> None:
        if self._processes[name].close():
            self.forget(name)

    def describe(self) -> list[dict[str, object]]:
        return [
            {"session": name, "pid": process.pid, "cleanup_pending": True}
            for name, process in self._processes.items()
        ]

    def pump(self) -> None:
        for name in list(self._processes):
            try:
                self.stop(name)
            except OSError as error:
                if name not in self._errors:
                    logger.exception("Terminal cleanup still pending for %s", name)
                self._errors[name] = error

    def close(self) -> list[Exception]:
        failures: list[Exception] = []
        for name in list(self._processes):
            try:
                self.stop(name)
            except (OSError, RuntimeError) as error:
                failures.append(error)
        deadline = time.monotonic() + 0.7
        while self._processes and time.monotonic() < deadline:
            self.pump()
            time.sleep(0.01)
        if self._processes:
            failures.extend(self._errors.values())
            failures.append(
                TimeoutError(f"terminal cleanup pending: {sorted(self._processes)}")
            )
        return failures
