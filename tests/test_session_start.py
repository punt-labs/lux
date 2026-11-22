"""The SessionStart event sink accepts only safe launch diagnostics."""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.session_start import AppletEvent, SessionStartDecisions


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
        SessionStartDecisions.record(event, 456)
    assert caplog.messages == [f"SessionStart applet {message} (child pid=456)"]


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
