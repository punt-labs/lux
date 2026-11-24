"""Peripheral contracts accept structural implementations without inheritance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import pytest

from punt_lux.hub.peripheral_ports import PeripheralStatus, PeripheralWorkers


@dataclass(frozen=True, slots=True)
class _Status:
    is_connected: bool


class _Workers:
    _events: list[str]

    def __new__(cls, events: list[str]) -> Self:
        self = super().__new__(cls)
        self._events = events
        return self

    def start(self) -> None:
        self._events.append("start")

    def stop(self) -> None:
        self._events.append("stop")


@pytest.mark.parametrize("connected", [False, True])
def test_status_is_satisfied_structurally(connected: bool) -> None:
    concrete = _Status(connected)
    status: PeripheralStatus = concrete
    assert status is concrete
    assert status.is_connected is connected


def test_workers_are_satisfied_structurally() -> None:
    events: list[str] = []
    concrete = _Workers(events)
    workers: PeripheralWorkers = concrete
    assert workers is concrete
    assert events == []
    workers.start()
    workers.stop()
    assert events == ["start", "stop"]
