"""The SessionStart event sink accepts only safe launch diagnostics."""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.applet_event import AppletEvent, AppletRecords


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (AppletEvent.INTENT, "launch intent: spawning"),
        (AppletEvent.LAUNCHED, "launched: spawned"),
        (AppletEvent.MISSING, "skipped: executable missing"),
        (AppletEvent.RUNNING, "skipped: already running"),
        (AppletEvent.PROBE_ERROR, "failed: process probe error"),
        (AppletEvent.SPAWN_ERROR, "failed: spawn error"),
    ],
)
def test_safe_event_vocabulary(
    caplog: pytest.LogCaptureFixture, event: AppletEvent, message: str
) -> None:
    with caplog.at_level(logging.INFO):
        AppletRecords.record(event, 456)
    suffix = (
        " (child pid=456)"
        if event in (AppletEvent.LAUNCHED, AppletEvent.SPAWN_ERROR)
        else ""
    )
    assert caplog.messages == [f"SessionStart applet {message}{suffix}"]
    assert caplog.records[0].levelno == (
        logging.WARNING
        if event in (AppletEvent.PROBE_ERROR, AppletEvent.SPAWN_ERROR)
        else logging.INFO
    )


@pytest.mark.parametrize("event", list(AppletEvent))
def test_absent_child_is_omitted(
    caplog: pytest.LogCaptureFixture, event: AppletEvent
) -> None:
    with caplog.at_level(logging.INFO):
        AppletRecords.record(event, 0)
    assert "child pid" not in caplog.messages[0]


@pytest.mark.parametrize("event", list(AppletEvent))
def test_event_command_stdout_is_empty(tmp_path: Path, event: AppletEvent) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "punt_lux", "hook", "applet-event", event.value],
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [[], ["/private/alice"], ["launched", "--child-pid", "-1"]],
)
def test_invalid_events_are_rejected(args: list[str]) -> None:
    result = CliRunner().invoke(app, ["hook", "applet-event", *args])
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("missing", "skipped: executable missing"),
        ("running", "skipped: already running"),
        ("probe-error", "failed: process probe error"),
        ("launch", "launched: spawned"),
    ],
)
def test_shell_records_decisions_without_standard_streams(
    tmp_path: Path, scenario: str, message: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "lux").symlink_to(Path(sys.executable).parent / "lux")
    if scenario != "missing":
        applet = bin_dir / "lux-beads"
        applet.write_text("#!/bin/sh\nsleep 1\n")
        applet.chmod(0o700)
    probe = bin_dir / "pgrep"
    probe.write_text(
        f"#!/bin/sh\nexit { {'running': 0, 'probe-error': 2}.get(scenario, 1) }\n"
    )
    probe.chmod(0o700)
    script = Path(__file__).resolve().parent.parent / "plugin/hooks/session-start.sh"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        input='{"hook_event_name":"SessionStart","session_id":"private-session"}',
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == 0
    path = tmp_path / ".punt-labs/lux/logs/lux.log"
    log = path.read_text()
    assert f"SessionStart applet {message}" in log
    assert ("launch intent: spawning" in log) == (scenario == "launch")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert str(tmp_path) not in log
    assert "private-session" not in log


@pytest.mark.parametrize("logger_state", ["missing", "failing"])
def test_logging_cannot_prevent_launch(tmp_path: Path, logger_state: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if logger_state == "failing":
        lux = bin_dir / "lux"
        lux.write_text("#!/bin/sh\necho noisy\necho noisy >&2\nexit 1\n")
        lux.chmod(0o700)
    captured = tmp_path / "launched"
    applet = bin_dir / "lux-beads"
    applet.write_text(f"#!/bin/sh\ntouch '{captured}'\n")
    applet.chmod(0o700)
    probe = bin_dir / "pgrep"
    probe.write_text("#!/bin/sh\nexit 1\n")
    probe.chmod(0o700)
    script = Path(__file__).resolve().parent.parent / "plugin/hooks/session-start.sh"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    deadline = time.monotonic() + 5
    while not captured.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert captured.exists()
