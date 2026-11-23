"""A persistent cleanup failure is logged once per session, not once per pump."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.pty.process_retirement import ProcessRetirement

if TYPE_CHECKING:
    import pytest


class _StuckProcess:
    pid = 42

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def close(self) -> bool:
        raise OSError("device busy")


def test_a_persistent_oserror_is_logged_once_and_stays_pending(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retirement = ProcessRetirement()
    retirement.add("shell", _StuckProcess())  # type: ignore[arg-type]  # fake port

    with caplog.at_level(logging.ERROR, logger="punt_lux.pty.process_retirement"):
        for _ in range(50):
            retirement.pump()

    assert len(caplog.records) == 1
    assert retirement.contains("shell")
