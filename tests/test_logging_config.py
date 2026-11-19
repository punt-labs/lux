"""Exercise Lux diagnostics using the real shared logging configuration."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_DIAGNOSTIC = """
import logging
from punt_lux.logging_config import configure_logging

configure_logging("lux", "worker")
logger = logging.getLogger("lux.test")
logger.debug("debug detail")
logger.info("record %s", "first\u2028forged")
try:
    raise ValueError("https://user:fake-test-password@example.com/")
except ValueError:
    logger.exception("diagnostic failure")
"""


@pytest.mark.parametrize("level", [None, "", "verbose is not a level", "debug"])
def test_entry_logging_is_private_and_sanitized(
    tmp_path: Path, level: str | None
) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env.pop("LUX_LOG_LEVEL", None)
    if level is not None:
        env["LUX_LOG_LEVEL"] = level
    result = subprocess.run(
        [sys.executable, "-c", _DIAGNOSTIC],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    path = tmp_path / ".punt-labs" / "lux" / "logs" / "lux.log"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    log = path.read_text()
    assert "record first\\u2028forged" in log
    assert "diagnostic failure" in log
    assert "fake-test-password" not in log + result.stderr
    assert not result.stdout
    assert ("debug detail" in log) == (level == "debug")
    assert ("Invalid LUX_LOG_LEVEL" in log) == (level == "verbose is not a level")
    assert "verbose is not a level" not in log


def test_detached_failure_is_durable_without_its_message(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from punt_lux.logging_config import process_diagnostics\n"
                "with process_diagnostics('worker', 'test worker'):\n"
                "    raise RuntimeError('private input')\n"
            ),
        ],
        stderr=subprocess.DEVNULL,
        check=False,
        env={**os.environ, "HOME": str(tmp_path), "LUX_LOG_LEVEL": "INFO"},
    )
    assert result.returncode == 1
    log = (tmp_path / ".punt-labs/lux/logs/lux.log").read_text()
    assert "test worker failed: RuntimeError" in log
    assert "<module>:3" in log
    assert "private input" not in log


def test_verbose_overrides_the_environment_level(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import logging\n"
                "from punt_lux.logging_config import configure_logging\n"
                "configure_logging('lux', 'cli', verbose=True)\n"
                "logging.getLogger('lux.test').debug('verbose detail')\n"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path), "LUX_LOG_LEVEL": "INFO"},
    )
    assert "verbose detail" in result.stderr
    assert "verbose detail" in (tmp_path / ".punt-labs/lux/logs/lux.log").read_text()
