"""Live clients or retained sessions prevent idle shutdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.ptyd.lifetime import DaemonLifetime

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_idle_requires_continuous_empty_interval(monkeypatch: MonkeyPatch) -> None:
    now = [0.0]

    def clock() -> float:
        return now[0]

    monkeypatch.setattr("punt_lux.ptyd.lifetime.time.monotonic", clock)
    timer = DaemonLifetime(1)
    assert not timer.expired(0, 0)
    now[0] = 2
    assert not timer.expired(0, 1)  # no viewer, but a program or exited screen remains
    assert not timer.expired(0, 0)
    now[0] = 4
    assert not timer.expired(1, 0)  # an attached control client also prevents shutdown
    assert not timer.expired(0, 0)
    now[0] = 6
    assert timer.expired(0, 0)
