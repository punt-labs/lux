"""Process lookups expose the caller's timeout without changing Hub defaults."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from punt_lux.service._backends import pgrep_pid


@pytest.mark.parametrize(
    "output,expected", [("502\n", 502), ("", None), ("bad\n", None)]
)
def test_pgrep_is_bounded_and_preserves_absence(
    output: str, expected: int | None
) -> None:
    with patch("punt_lux.service._backends.subprocess.run") as run:
        run.return_value.stdout = output
        assert pgrep_pid("luxd-display", timeout=0.125) == expected
    assert run.call_args.kwargs["timeout"] == 0.125


def test_pgrep_timeout_is_not_confused_with_an_absent_process() -> None:
    with patch(
        "punt_lux.service._backends.subprocess.run",
        side_effect=subprocess.TimeoutExpired("pgrep", 0.125),
    ), pytest.raises(subprocess.TimeoutExpired):
        pgrep_pid("luxd-display", timeout=0.125)
