"""Exercise Lux diagnostics using the real shared logging configuration."""

from __future__ import annotations

import logging
import os
import signal
import stat
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from punt_lux.kernel.logging_config import record_signal

if TYPE_CHECKING:
    from pathlib import Path

_DIAGNOSTIC = """
import logging
from punt_lux.kernel.logging_config import configure_logging

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
                "from punt_lux.kernel.logging_config import process_diagnostics\n"
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
                "from punt_lux.kernel.logging_config import configure_logging\n"
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


_DAEMON = """
import sys
import time
from punt_lux.kernel.logging_config import process_diagnostics

with process_diagnostics("daemon", "probe daemon"):
    print("ready", flush=True)
    time.sleep(60)
"""


def _log(home: Path) -> str:
    return (home / ".punt-labs/lux/logs/lux.log").read_text()


def _signalled_daemon(home: Path, signum: int) -> tuple[int, str]:
    process = subprocess.Popen(
        [sys.executable, "-c", _DAEMON],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "HOME": str(home), "LUX_LOG_LEVEL": "INFO"},
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    process.send_signal(signum)
    return process.wait(timeout=30), _log(home)


def test_a_daemon_terminated_by_sigterm_logs_the_signal_and_its_exit(
    tmp_path: Path,
) -> None:
    code, log = _signalled_daemon(tmp_path, signal.SIGTERM)
    assert code == 128 + signal.SIGTERM
    assert "probe daemon started (pid=" in log
    assert "received SIGTERM" in log
    assert "probe daemon exiting: exit 143" in log


def test_a_daemon_hung_up_by_sighup_logs_the_signal_and_its_exit(
    tmp_path: Path,
) -> None:
    code, log = _signalled_daemon(tmp_path, signal.SIGHUP)
    assert code == 128 + signal.SIGHUP
    assert "received SIGHUP" in log
    assert "probe daemon exiting: exit 129" in log


def test_a_daemon_that_returns_logs_a_normal_exit(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from punt_lux.kernel.logging_config import process_diagnostics\n"
                "with process_diagnostics('daemon', 'probe daemon'):\n"
                "    pass\n"
            ),
        ],
        check=True,
        env={**os.environ, "HOME": str(tmp_path), "LUX_LOG_LEVEL": "INFO"},
    )
    assert "probe daemon exiting: normal return" in _log(tmp_path)


def test_a_daemon_that_fails_logs_the_failure_and_an_error_exit(
    tmp_path: Path,
) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from punt_lux.kernel.logging_config import process_diagnostics\n"
                "with process_diagnostics('daemon', 'probe daemon'):\n"
                "    raise RuntimeError('private input')\n"
            ),
        ],
        check=False,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "HOME": str(tmp_path), "LUX_LOG_LEVEL": "INFO"},
    )
    log = _log(tmp_path)
    assert "probe daemon failed: RuntimeError" in log
    assert "probe daemon exiting: error" in log
    assert "private input" not in log


def test_a_handler_that_stops_a_daemon_records_the_signal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    record_signal(signal.SIGTERM)
    assert any(
        "received SIGTERM" in r.getMessage() and str(os.getpid()) in r.getMessage()
        for r in caplog.records
    )
