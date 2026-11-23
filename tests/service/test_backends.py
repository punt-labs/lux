"""Process lookups have a fixed bounded subprocess timeout."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from punt_lux.service._backends import PGREP_TIMEOUT, pgrep_pid


@pytest.mark.parametrize(
    "output,expected", [("502\n", 502), ("", None), ("bad\n", None), ("-5\n", None)]
)
def test_pgrep_is_bounded_and_preserves_absence(
    output: str, expected: int | None
) -> None:
    with patch("punt_lux.service._backends.subprocess.run") as run:
        run.return_value.stdout = output
        assert pgrep_pid("luxd-display") == expected
    assert run.call_args.kwargs["timeout"] == PGREP_TIMEOUT


def test_pgrep_timeout_is_not_confused_with_an_absent_process() -> None:
    with (
        patch(
            "punt_lux.service._backends.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pgrep", PGREP_TIMEOUT),
        ),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        pgrep_pid("luxd-display")
